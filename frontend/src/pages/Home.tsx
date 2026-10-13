import BackendStatus from '../components/BackendStatus'
import RepositoryIngestion from '../components/RepositoryIngestion'

export default function Home() {
  return (
    <div className="space-y-14">
      <RepositoryIngestion />
      <BackendStatus />
    </div>
  )
}
