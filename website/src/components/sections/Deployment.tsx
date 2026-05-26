import { motion } from "framer-motion"

export function Deployment() {
  return (
    <section id="deployment" className="py-20">
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="max-w-3xl"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            Future Commercial Deployment Options
          </p>
          <p className="mb-4 text-base leading-relaxed text-site-muted">
            Once validated and ready for deployment, AxiOMSphere is intended to be configurable to
            each client's scale, confidentiality requirements and operating model. Future delivery
            options may include deployment on client-owned private infrastructure, dedicated hosted
            environments or controlled pilot use of approved cloud computing resources. Platform
            configuration and commercial scope may scale with the number of authorised users,
            projects, departments and required workloads, while protected project identity and
            source-document boundaries remain controlled within the client environment.
          </p>
          <p className="text-sm italic text-site-subtle">
            Post-validation product perspective only. No commercial deployment or customer pilot is
            claimed at the current development stage.
          </p>
        </motion.div>
      </div>
    </section>
  )
}
