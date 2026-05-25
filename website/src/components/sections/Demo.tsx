import { motion } from "framer-motion"

export function Demo() {
  return (
    <section
      id="demo"
      className="border-y border-[rgba(100,130,200,0.1)] bg-site-surface py-20"
    >
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mx-auto max-w-3xl"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            Product Walkthrough
          </p>
          <h2 className="mb-3 text-2xl font-bold leading-tight tracking-tight text-site-text md:text-3xl">
            A recorded walkthrough of the current applied stage.
          </h2>
          <p className="mb-6 text-base leading-relaxed text-site-muted">
            A recorded development-stage walkthrough of the current AIMS work-product interaction
            surface.
          </p>

          {/* Video */}
          <div className="overflow-hidden rounded-2xl border border-[rgba(100,130,200,0.15)] bg-site-card shadow-[0_4px_40px_rgba(0,0,0,0.4)]">
            <video
              className="w-full"
              controls
              preload="metadata"
              aria-label="AxiOMSphere demo walkthrough"
            >
              <source src="docs/demo.mp4" type="video/mp4" />
              Your browser does not support the video tag.
            </video>
          </div>

          <p className="mt-4 text-xs text-site-subtle">
            Demonstration scenario only. Outputs require qualified human review before operational
            use.
          </p>
        </motion.div>
      </div>
    </section>
  )
}
