import { useState } from "react"
import { motion, useReducedMotion } from "framer-motion"
import { ChevronRight } from "lucide-react"
import { capabilityCards, type CapabilityCard } from "@/data/public-content"
import {
  AccordionRoot,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion"
import { cn } from "@/lib/utils"

export function CapabilityCards() {
  return (
    <section
      id="capabilities"
      className="border-b border-[rgba(100,130,200,0.1)] bg-site-bg py-20"
    >
      {/* Section heading — eyebrow label pending founder approval before making it visible */}
      <h2 className="sr-only">AxiOMSphere Capabilities and Challenges</h2>

      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, delay: 0.1 }}
        >
          <AccordionRoot className="space-y-2">
            {capabilityCards.map((card, index) => (
              <CapabilityCardItem key={card.id} card={card} index={index} />
            ))}
          </AccordionRoot>
        </motion.div>
      </div>
    </section>
  )
}

function CapabilityCardItem({ card, index }: { card: CapabilityCard; index: number }) {
  return (
    <AccordionItem
      id={card.id}
      className={cn(
        "overflow-hidden rounded-xl border border-[rgba(100,130,200,0.12)] bg-site-card",
        "transition-colors duration-200",
        "data-[open]:border-[rgba(14,165,233,0.2)]",
      )}
    >
      <AccordionTrigger className="px-5 py-4 hover:bg-[rgba(255,255,255,0.02)] transition-colors duration-150 rounded-t-xl">
        <span className="flex min-w-0 items-center gap-3">
          <span
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[rgba(14,165,233,0.1)] text-xs font-bold text-site-accent"
            aria-hidden="true"
          >
            {index + 1}
          </span>
          <span className="text-sm font-semibold leading-snug text-site-text sm:text-base">
            {card.title}
          </span>
        </span>
      </AccordionTrigger>

      <AccordionContent>
        <div className="space-y-5 border-t border-[rgba(100,130,200,0.08)] px-5 pb-6 pt-4 pl-[3.25rem]">
          {/* Status */}
          <div>
            <p className="mb-1 text-xs font-bold uppercase tracking-wider text-site-subtle">
              Status
            </p>
            <p className="text-sm text-site-accent">{card.status}</p>
          </div>

          {/* How AxiOMSphere supports this challenge */}
          <div>
            <p className="mb-2 text-xs font-bold uppercase tracking-wider text-site-subtle">
              How AxiOMSphere supports this challenge
            </p>
            <p className="text-sm leading-relaxed text-site-muted">{card.support}</p>
          </div>

          {/* What this covers — nested disclosure */}
          <CoversDisclosure cardId={card.id} covers={card.covers} />
        </div>
      </AccordionContent>
    </AccordionItem>
  )
}

function CoversDisclosure({ cardId, covers }: { cardId: string; covers: string[] }) {
  const [open, setOpen] = useState(false)
  const prefersReducedMotion = useReducedMotion() ?? false

  return (
    <div className="overflow-hidden rounded-lg border border-[rgba(100,130,200,0.1)] bg-[rgba(255,255,255,0.018)]">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${cardId}-covers`}
        id={`${cardId}-covers-trigger`}
        onClick={() => setOpen(!open)}
        className={cn(
          "flex w-full items-center justify-between gap-3 px-4 py-3 text-left",
          "text-xs font-bold uppercase tracking-wider text-site-muted",
          "hover:bg-[rgba(255,255,255,0.025)] transition-colors duration-150",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-site-accent focus-visible:rounded-lg",
        )}
      >
        What this covers
        <ChevronRight
          size={14}
          className={cn(
            "shrink-0 text-site-subtle transition-transform duration-250",
            open && "rotate-90",
          )}
          aria-hidden="true"
        />
      </button>

      <motion.div
        id={`${cardId}-covers`}
        role="region"
        aria-labelledby={`${cardId}-covers-trigger`}
        aria-hidden={!open}
        initial={prefersReducedMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
        animate={
          open
            ? prefersReducedMotion
              ? { opacity: 1 }
              : { height: "auto", opacity: 1 }
            : prefersReducedMotion
              ? { opacity: 0 }
              : { height: 0, opacity: 0 }
        }
        transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
        style={{ overflow: "hidden" }}
      >
        <ul className="space-y-2.5 border-t border-[rgba(100,130,200,0.08)] px-4 pb-4 pt-3">
          {covers.map((item, i) => (
            <li key={i} className="flex items-start gap-2.5 text-sm leading-relaxed text-site-muted">
              <span
                className="mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full bg-site-accent/40"
                aria-hidden="true"
              />
              {item}
            </li>
          ))}
        </ul>
      </motion.div>
    </div>
  )
}
