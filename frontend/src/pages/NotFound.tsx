import { Link } from 'react-router'
import { Button, Card, EmptyState, PageHeading } from '../components/ui'

export default function NotFound() {
  return (
    <>
      <PageHeading eyebrow="404" title="No such page" />
      <Card>
        <EmptyState
          title="Nothing is here"
          body="The address does not match any screen in this application."
          action={
            <Link to="/">
              <Button>Back to the pipeline</Button>
            </Link>
          }
        />
      </Card>
    </>
  )
}
