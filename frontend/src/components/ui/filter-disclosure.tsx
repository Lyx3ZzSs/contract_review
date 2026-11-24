import { useId, useState, type ReactNode } from 'react'

type TriggerProps = {
  'aria-expanded': boolean
  'aria-controls': string
  onClick: () => void
}

// Opening filters should only update their controls, even beside a long result list.
export function FilterDisclosure({ toolbar, panelClassName, children }: {
  toolbar: (trigger: TriggerProps) => ReactNode
  panelClassName: string
  children: ReactNode
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  return <>
    {toolbar({ 'aria-expanded': open, 'aria-controls': id, onClick: () => setOpen(value => !value) })}
    <div id={id} className={panelClassName} hidden={!open} inert={!open}>{children}</div>
  </>
}
