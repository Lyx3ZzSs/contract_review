import type { ReactNode } from 'react'

// Adapted from ReUI data-grid-base-5 / support-queue-card.tsx.
// Retains the template's header → toolbar/table → pagination composition.
export function ContractQueueCard({title, description, action, children, footer}: {
  title: string; description: ReactNode; action?: ReactNode; children: ReactNode; footer?: ReactNode
}) {
  return <section className="contract-queue-card" aria-label={title}>
    <header className="contract-queue-heading"><div><h2>{title}</h2><p>{description}</p></div>{action}</header>
    <div>{children}</div>
    {footer&&<footer className="contract-queue-footer">{footer}</footer>}
  </section>
}
