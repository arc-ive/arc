import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Card } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Avatar } from '../../components/ui/Avatar.jsx'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '../../components/ui/Table.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { formatDate } from '../../lib/format.js'

export function TenantUsersPage() {
  const { tenantId } = useParams()
  const { isDemo } = useAuth()

  const users = useQuery({
    queryKey: queryKeys.tenantUsers(tenantId),
    queryFn: () => getTenantUsers(tenantId),
    enabled: !isDemo && Boolean(tenantId),
  })

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
          Tenant users
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Users with membership in this tenant, as authorized by the backend.
        </p>
      </section>

      {users.isPending && (
        <Card className="p-5">
          <div className="flex flex-col gap-4">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="size-8 rounded-full" />
                <div className="flex flex-1 flex-col gap-1.5">
                  <Skeleton className="h-3.5 w-1/3" />
                  <Skeleton className="h-3 w-1/4" />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {users.isError && (
        <Card>
          <ErrorState
            title="Could not load tenant users"
            message={errorMessage(users.error)}
            onRetry={() => users.refetch()}
            error={users.error}
          />
        </Card>
      )}

      {users.data?.length === 0 && (
        <Card>
          <EmptyState
            icon={Users}
            title="No users in this tenant"
            description="Memberships are provisioned by the backend. No user has been assigned to this tenant yet."
          />
        </Card>
      )}

      {users.data?.length > 0 && (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Username</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <Avatar name={user.email} size="sm" />
                      <div className="min-w-0">
                        <p className="truncate font-medium text-zinc-100">
                          {user.email}
                        </p>
                        <p className="truncate font-mono text-xs text-zinc-600">
                          {user.id}
                        </p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {user.username ?? '—'}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={user.status === 'active' ? 'green' : 'neutral'}
                      size="sm"
                      dot
                    >
                      {user.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-zinc-500">
                    {formatDate(user.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}