import { motion } from "framer-motion"
import { ShieldCheck } from "lucide-react"

export function Framework() {
  return (
    <section id="framework" className="py-20">
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="max-w-3xl"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            Management-System Framework and Responsible Data Boundary
          </p>

          {/* Standards strip */}
          <div className="mb-5 flex flex-wrap gap-2">
            {[
              "ISO 55001 requirements",
              "ISO 55002 guidance",
              "GFMAM Asset Management Landscape reference",
            ].map((s) => (
              <span
                key={s}
                className="rounded-full border border-[rgba(14,165,233,0.25)] bg-[rgba(14,165,233,0.06)] px-3 py-1 text-xs font-medium text-site-accent"
              >
                {s}
              </span>
            ))}
          </div>

          <p className="mb-5 text-base leading-relaxed text-site-muted">
            Project source documents remain on private infrastructure. Where external evaluation is
            authorised, only anonymised generated outputs or de-identified evaluation context may
            be submitted for assessment of structure and framework alignment, without
            project-identifying information.
          </p>

          {/* Callout */}
          <div className="flex items-start gap-3 rounded-xl border border-[rgba(14,165,233,0.15)] bg-[rgba(14,165,233,0.04)] p-4">
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-site-accent" />
            <p className="text-sm leading-relaxed text-site-muted">
              All generated outputs remain recommendations until reviewed and approved by qualified
              specialists for their intended use.
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
