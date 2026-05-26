import { motion } from "framer-motion"

export function WhatIs() {
  return (
    <section id="what-is" className="border-b border-[rgba(100,130,200,0.1)] bg-site-surface py-20">
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            What Is AxiOMSphere
          </p>
          <div className="max-w-3xl space-y-4">
            <p className="text-base leading-relaxed text-site-muted">
              AxiOMSphere is a development-stage multi-agent platform that coordinates specialised
              AI agents throughout the evolution of an industrial operating organisation: first, to
              develop the structured documents and work products required for project startup; then,
              to organise and synchronise departmental functions, responsibilities and interfaces;
              and, as the organisation matures, to support company specialists in developing,
              reviewing and updating the management system in alignment with company standards,
              applicable industry regulations and shareholder expectations.
            </p>
            <p className="text-base leading-relaxed text-site-muted">
              AxiOMSphere coordinates specialised AI agents to develop project-startup work
              products, align departmental functions and interfaces, and support company specialists
              in continuously developing and updating the management system in accordance with
              company standards, applicable industry regulations and shareholder expectations.
            </p>
            <p className="text-base leading-relaxed text-site-muted">
              The platform follows ISO 55001 requirements and ISO 55002 guidance as its AIMS
              management-system framework basis. It is structured around the GFMAM Asset Management
              Landscape as its broader process-framework reference.
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
