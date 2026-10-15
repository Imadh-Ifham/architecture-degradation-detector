"""Component identity resolution.

Author: Imadh Ifham
Date: 2026-10-15
Description:
    Decides which candidate artifacts describe the *same* logical component, and
    records why.

    Merging is driven by a small set of named rules applied in priority order.
    Each rule is either direct (machine-checkable from the inputs) or heuristic
    (suggestive only), so the resulting components carry an honest confidence and
    a consumer can see exactly which evidence held them together.

    Two guards exist specifically to prevent unsafe merging:

      * A repository-root location is never treated as evidence of containment.
        "Everything is under the repository root" would otherwise merge an entire
        repository into a single component.
      * Base images are not identity evidence, so two unrelated Dockerfiles that
        happen to share a base image stay separate.

    The result is a partition, not a single component: candidates that no rule
    connects stay separate, which is the desired outcome for unrelated artifacts.
"""

from dataclasses import dataclass, field

from app.components.architecture_recovery.component_discovery.candidates import (
    KUBERNETES_SERVICE,
    Candidate,
)
from app.components.architecture_recovery.component_discovery.models import (
    AssociationConfidence,
    MergeRule,
    confidence_for_rule,
    weakest_confidence,
)
from app.components.architecture_recovery.component_discovery.paths import (
    ROOT_DIRECTORY,
    is_within,
)


@dataclass(frozen=True)
class MergeDecision:
    """One applied merge, recorded so the component can explain itself."""

    rule: MergeRule
    detail: str
    left_id: str
    right_id: str

    @property
    def confidence(self) -> AssociationConfidence:
        """Return the confidence implied by the rule that produced this merge."""

        return confidence_for_rule(self.rule)


@dataclass
class IdentityGroup:
    """A set of candidates resolved to one logical component."""

    candidate_ids: list[str] = field(default_factory=list)
    decisions: list[MergeDecision] = field(default_factory=list)

    def confidence(self) -> AssociationConfidence:
        """Return the weakest confidence among the merges that formed the group.

        A component is only as trustworthy as its weakest link, so one heuristic
        merge caps the whole component at heuristic.
        """

        confidences = [decision.confidence for decision in self.decisions]

        if not confidences:
            # A single candidate needs no merge to justify it; its own artifact
            # confidence is used instead by the caller.
            return AssociationConfidence.DIRECT

        return weakest_confidence(confidences)


class UnionFind:
    """Disjoint-set structure used to partition candidates into components."""

    def __init__(self, keys: list[str]) -> None:
        """Initialise every key as its own set."""

        self._parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        """Return the representative of the set containing `key`."""

        root = key

        while self._parent[root] != root:
            root = self._parent[root]

        # Path compression keeps repeated lookups cheap.
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]

        return root

    def union(self, left: str, right: str) -> str:
        """Join two sets and return the surviving representative.

        The representative is chosen deterministically (lexicographically
        smallest) so the partition does not depend on union order.
        """

        left_root = self.find(left)
        right_root = self.find(right)

        if left_root == right_root:
            return left_root

        winner, loser = sorted((left_root, right_root))
        self._parent[loser] = winner

        return winner


class IdentityResolver:
    """Partitions candidate artifacts into logical components."""

    def __init__(self) -> None:
        """Initialise the resolver."""

        self._decisions: dict[str, list[MergeDecision]] = {}

    def resolve(self, candidates: list[Candidate]) -> list[IdentityGroup]:
        """Return the identity groups the candidates resolve into."""

        ordered = sorted(candidates, key=lambda item: item.artifact.id)

        union_find = UnionFind([candidate.artifact.id for candidate in ordered])
        self._decisions = {candidate.artifact.id: [] for candidate in ordered}

        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                decision = self._rule_for(left, right)

                if decision is None:
                    continue

                union_find.union(left.artifact.id, right.artifact.id)
                self._decisions[left.artifact.id].append(decision)
                self._decisions[right.artifact.id].append(decision)

        grouped: dict[str, list[str]] = {}

        for candidate in ordered:
            grouped.setdefault(union_find.find(candidate.artifact.id), []).append(
                candidate.artifact.id
            )

        return [
            IdentityGroup(
                candidate_ids=sorted(candidate_ids),
                decisions=sorted(
                    {
                        decision
                        for candidate_id in candidate_ids
                        for decision in self._decisions.get(candidate_id, [])
                    },
                    key=lambda item: (item.rule.value, item.left_id, item.right_id),
                ),
            )
            for _, candidate_ids in sorted(grouped.items())
        ]

    def _rule_for(self, left: Candidate, right: Candidate) -> MergeDecision | None:
        """Return the highest-priority rule that merges two candidates."""

        for rule_function in (
            self._build_context,
            self._project_containment,
            self._shared_image,
            self._name_and_location,
            self._name_only,
        ):
            decision = rule_function(left, right)

            if decision is not None:
                return decision

        return None

    # ------------------------------------------------------------------ #
    # Rules, highest priority first
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_context(left: Candidate, right: Candidate) -> MergeDecision | None:
        """Merge a deployment that declares a build context with what it builds.

        The declared context is an explicit statement that the artifacts under it
        implement that service, so the link is direct. A context of the
        repository root is skipped: it claims everything, so it distinguishes
        nothing.
        """

        for deployment, other in ((left, right), (right, left)):
            if not deployment.build_contexts:
                continue

            if not other.has_location:
                continue

            for context in deployment.build_contexts:
                if context == ROOT_DIRECTORY:
                    continue

                if is_within(other.directory, context):
                    return MergeDecision(
                        rule=MergeRule.BUILD_CONTEXT_CONTAINMENT,
                        detail=(
                            f"'{other.artifact.path}' lies inside the build context "
                            f"'{context}' declared by '{deployment.artifact.name}'"
                        ),
                        left_id=left.artifact.id,
                        right_id=right.artifact.id,
                    )

        return None

    @staticmethod
    def _project_containment(left: Candidate, right: Candidate) -> MergeDecision | None:
        """Merge a source project with the located artifacts inside it.

        A project root owning a directory is machine-checkable evidence that the
        artifacts under it belong to that project rather than to a different one.
        A project rooted at the repository root is skipped, for the same reason as
        a root build context.
        """

        for project, other in ((left, right), (right, left)):
            if not project.is_project or not project.root_path:
                continue

            if project.root_path == ROOT_DIRECTORY:
                continue

            if not other.has_location or other is project:
                continue

            if is_within(other.directory, project.root_path):
                return MergeDecision(
                    rule=MergeRule.PROJECT_LOCATION_CONTAINMENT,
                    detail=(
                        f"'{other.artifact.path}' lies inside the project root "
                        f"'{project.root_path}'"
                    ),
                    left_id=left.artifact.id,
                    right_id=right.artifact.id,
                )

        return None

    @staticmethod
    def _shared_image(left: Candidate, right: Candidate) -> MergeDecision | None:
        """Merge two deployments that run the same application image.

        Only application images count, so two Dockerfiles sharing a base image
        do not merge.
        """

        shared = left.images & right.images

        if not shared:
            return None

        image = sorted(shared)[0]

        return MergeDecision(
            rule=MergeRule.SHARED_IMAGE_REFERENCE,
            detail=f"both artifacts run the image '{image}'",
            left_id=left.artifact.id,
            right_id=right.artifact.id,
        )

    @staticmethod
    def _name_and_location(left: Candidate, right: Candidate) -> MergeDecision | None:
        """Merge candidates whose names match and whose locations agree."""

        shared = left.keys & right.keys

        if not shared:
            return None

        if not (left.has_location and right.has_location):
            return None

        related = (
            left.directory == right.directory
            or is_within(left.directory, right.root_path)
            or is_within(right.directory, left.root_path)
            or is_within(left.directory, right.directory)
            or is_within(right.directory, left.directory)
        )

        if not related:
            return None

        return MergeDecision(
            rule=MergeRule.NAME_AND_LOCATION_MATCH,
            detail=(
                f"'{left.artifact.name}' and '{right.artifact.name}' share the name "
                f"'{sorted(shared)[0]}' and a location relationship"
            ),
            left_id=left.artifact.id,
            right_id=right.artifact.id,
        )

    @staticmethod
    def _name_only(left: Candidate, right: Candidate) -> MergeDecision | None:
        """Merge candidates whose identity keys intersect.

        This is the weakest rule: a name match with no corroborating location. It
        is what links a Kubernetes workload called `cartservice` to a source
        project whose directory is also `cartservice`, and it is why those
        components are reported as heuristic rather than direct.

        Two candidates that are *both* located at unrelated directories are not
        merged, even when their names match. Two distinct projects called
        `frontend` in different parts of a repository are two components, not one;
        merging them would be inventing a boundary out of a shared name. The
        conflict is reported as a duplicate identity instead.
        """

        if KUBERNETES_SERVICE in (left.kind, right.kind):
            # A Service carries no identity keys and never merges by name.
            return None

        shared = left.keys & right.keys

        if not shared:
            return None

        if left.has_location and right.has_location:
            related = (
                left.directory == right.directory
                or is_within(left.directory, right.root_path)
                or is_within(right.directory, left.root_path)
                or is_within(left.directory, right.directory)
                or is_within(right.directory, left.directory)
            )

            if not related:
                return None

        key = sorted(shared)[0]

        return MergeDecision(
            rule=MergeRule.NAME_MATCH,
            detail=(
                f"'{left.artifact.name or left.kind}' and "
                f"'{right.artifact.name or right.kind}' share the identity key "
                f"'{key}'"
            ),
            left_id=left.artifact.id,
            right_id=right.artifact.id,
        )
