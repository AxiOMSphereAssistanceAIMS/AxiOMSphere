import { createContext, useContext, useState, type ReactNode } from "react"
import { motion, useReducedMotion } from "framer-motion"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

// ---- Root context: tracks which item is open (one at a time) ----

interface AccordionCtx {
  openId: string | null
  setOpenId: (id: string | null) => void
  prefersReducedMotion: boolean
}

const AccordionContext = createContext<AccordionCtx>({
  openId: null,
  setOpenId: () => {},
  prefersReducedMotion: false,
})

interface AccordionRootProps {
  children: ReactNode
  className?: string
}

export function AccordionRoot({ children, className }: AccordionRootProps) {
  const [openId, setOpenId] = useState<string | null>(null)
  const prefersReducedMotion = useReducedMotion() ?? false

  return (
    <AccordionContext.Provider value={{ openId, setOpenId, prefersReducedMotion }}>
      <div className={className}>{children}</div>
    </AccordionContext.Provider>
  )
}

// ---- Item context: exposes this item's id, open state, and toggle ----

interface AccordionItemCtx {
  itemId: string
  isOpen: boolean
  toggle: () => void
  prefersReducedMotion: boolean
}

const AccordionItemContext = createContext<AccordionItemCtx>({
  itemId: "",
  isOpen: false,
  toggle: () => {},
  prefersReducedMotion: false,
})

interface AccordionItemProps {
  id: string
  children: ReactNode
  className?: string
}

export function AccordionItem({ id, children, className }: AccordionItemProps) {
  const { openId, setOpenId, prefersReducedMotion } = useContext(AccordionContext)
  const isOpen = openId === id
  const toggle = () => setOpenId(isOpen ? null : id)

  return (
    <AccordionItemContext.Provider value={{ itemId: id, isOpen, toggle, prefersReducedMotion }}>
      <div className={className}>{children}</div>
    </AccordionItemContext.Provider>
  )
}

// ---- Trigger: accessible button with aria-expanded ----

interface AccordionTriggerProps {
  children: ReactNode
  className?: string
}

export function AccordionTrigger({ children, className }: AccordionTriggerProps) {
  const { isOpen, toggle, itemId } = useContext(AccordionItemContext)

  return (
    <button
      type="button"
      aria-expanded={isOpen}
      aria-controls={`${itemId}-content`}
      id={`${itemId}-trigger`}
      onClick={toggle}
      className={cn(
        "flex w-full items-center justify-between gap-4 text-left",
        "rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-site-accent",
        className,
      )}
    >
      {children}
      <ChevronDown
        size={18}
        className={cn(
          "shrink-0 text-site-subtle transition-transform duration-300",
          isOpen && "rotate-180",
        )}
        aria-hidden="true"
      />
    </button>
  )
}

// ---- Content: animated collapse/expand ----

interface AccordionContentProps {
  children: ReactNode
  className?: string
}

export function AccordionContent({ children, className }: AccordionContentProps) {
  const { isOpen, itemId, prefersReducedMotion } = useContext(AccordionItemContext)

  return (
    <motion.div
      id={`${itemId}-content`}
      role="region"
      aria-labelledby={`${itemId}-trigger`}
      aria-hidden={!isOpen}
      initial={{ height: 0, opacity: 0 }}
      animate={isOpen ? { height: "auto", opacity: 1 } : { height: 0, opacity: 0 }}
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : { duration: 0.28, ease: [0.4, 0, 0.2, 1] }
      }
      style={{ overflow: "hidden" }}
      className={className}
    >
      {children}
    </motion.div>
  )
}
