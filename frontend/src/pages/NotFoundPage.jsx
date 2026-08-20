import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { EmptyState } from '../components/ui/EmptyState.jsx'
import { Button } from '../components/ui/Button.jsx'
import { Card } from '../components/ui/Card.jsx'

export function NotFoundPage() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-2xl items-center justify-center">
      <Card className="w-full">
        <EmptyState
          icon={Compass}
          title="Page not found"
          description="The page you are looking for does not exist or has moved."
          action={
            <Link to="/app/dashboard">
              <Button variant="secondary" size="sm">
                Back to dashboard
              </Button>
            </Link>
          }
        />
      </Card>
    </div>
  )
}