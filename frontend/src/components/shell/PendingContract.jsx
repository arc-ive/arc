import { Badge } from '../ui/Badge.jsx'
import { Card, CardContent, CardHeader } from '../ui/Card.jsx'

/**
 * Honest shell state for product areas whose backend contract does not
 * exist yet. Renders a clearly marked "not yet available" surface instead
 * of fabricated data.
 */
export function PendingContract({
  title = 'Not yet available',
  description = 'The backend contract for this area has not been implemented.',
  children,
}) {
  return (
    <Card>
      <CardHeader title={title} description={description} />
      <CardContent>
        <div className="flex flex-col gap-4">
          <div>
            <Badge variant="amber" dot>
              Backend contract pending
            </Badge>
          </div>
          {children}
        </div>
      </CardContent>
    </Card>
  )
}