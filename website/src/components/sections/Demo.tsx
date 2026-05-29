import { motion } from "framer-motion"
import { demoShowcase } from "@/data/public-content"

export function Demo() {
  return (
    <section
      id="demo"
      className="border-b border-[rgba(100,130,200,0.1)] bg-site-surface py-20"
    >
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mx-auto max-w-4xl"
        >
          {/* Status label */}
          <p className="mb-3 text-center text-xs font-bold uppercase tracking-widest text-site-accent">
            {demoShowcase.statusLabel}
          </p>

          {/* Title */}
          <h2 className="mb-8 text-center text-2xl font-bold leading-tight tracking-tight text-site-text md:text-3xl">
            {demoShowcase.title}
          </h2>

          {/* Video showcase */}
          <div className="overflow-hidden rounded-2xl border border-[rgba(100,130,200,0.15)] bg-site-card shadow-[0_4px_40px_rgba(0,0,0,0.4)]">
            <video
              className="w-full"
              controls
              preload="metadata"
              aria-label="AxiOMSphere demo — on-demand AIMS document preparation and review"
            >
              <source src="docs/demo.mp4?v=4" type="video/mp4" />
              Your browser does not support the video tag.
            </video>
          </div>

          {/* Explanatory text below video */}
          <p className="mt-6 text-base leading-relaxed text-site-muted">
            {demoShowcase.belowVideoText}
          </p>
        </motion.div>
      </div>
    </section>
  )
}
