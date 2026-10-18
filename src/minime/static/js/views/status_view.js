/** Map an observed backend state to a visual token without changing its label. */
export function getStatusBadgeClass(status) {
  switch (status) {
    case 'READY':
    case 'READY_FOR_HUMAN_MERGE': return 'badge-ready';
    case 'RUNNING': return 'badge-running';
    case 'WAITING':
    case 'WAITING_CAPACITY': return 'badge-waiting';
    case 'NEEDS_HUMAN':
    case 'AUTH_REQUIRED': return 'badge-needs-human';
    case 'RECOVERY': return 'badge-recovery';
    case 'PAUSED': return 'badge-paused';
    case 'UNKNOWN': return 'badge-unknown';
    case 'COMPLETED': return 'badge-completed';
    case 'FAILED': return 'badge-failed';
    case 'NOT_READY': return 'badge-not-ready';
    default: return 'badge-discovered';
  }
}
