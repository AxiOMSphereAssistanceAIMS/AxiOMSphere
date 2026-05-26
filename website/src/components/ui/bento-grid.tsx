import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

export interface BentoItem {
  title: string
  description: string
  icon: ReactNode
  status?: string
  tags?: string[]
  meta?: string
  cta?: string
  colSpan?: 1 | 2
  hasPersistentHover?: boolean
}

interface BentoGridProps {
  items: BentoItem[]
  className?: string
}

export function BentoGrid({ items, className }: BentoGridProps) {
  return (
    <div className={cn("grid grid-cols-1 md:grid-cols-3 gap-4", className)}>
      {items.map((item, i) => (
        <BentoCard key={i} item={item} />
      ))}
    </div>
  )
}

function BentoCard({ item }: { item: BentoItem }) {
  return (
    <article
      className={cn(
        "group relative flex flex-col gap-3 rounded-2xl border border-[rgba(100,130,200,0.12)] bg-site-card p-6 transition-all duration-300",
        "hover:border-[rgba(14,165,233,0.28)] hover:shadow-[0_0_28px_rgba(14,165,233,0.08)]",
        item.hasPersistentHover && "border-[rgba(14,165,233,0.2)] shadow-[0_0_20px_rgba(14,165,233,0.06)]",
        item.colSpan === 2 && "md:col-span-2",
      )}
    >
      {/* Icon */}
      <div className="flex items-center justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[rgba(14,165,233,0.1)] text-site-accent">
          {item.icon}
        </div>
        {item.status && (
          <span className="rounded-full border border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.08)] px-2.5 py-0.5 text-xs font-medium text-site-green">
            {item.status}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex flex-col gap-1.5">
        <h3 className="text-base font-semibold text-site-text">{item.title}</h3>
        <p className="text-sm leading-relaxed text-site-muted">{item.description}</p>
      </div>

      {/* Tags */}
      {item.tags && item.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {item.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-md border border-[rgba(100,130,200,0.15)] bg-[rgba(255,255,255,0.03)] px-2 py-0.5 text-xs text-site-subtle"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Meta / CTA */}
      {(item.meta || item.cta) && (
        <div className="mt-auto flex items-center justify-between pt-2">
          {item.meta && <span className="text-xs text-site-subtle">{item.meta}</span>}
          {item.cta && (
            <span className="text-xs font-medium text-site-accent opacity-0 transition-opacity duration-200 group-hover:opacity-100">
              {item.cta} →
            </span>
          )}
        </div>
      )}
    </article>
  )
}
