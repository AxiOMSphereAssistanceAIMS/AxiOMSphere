import { motion } from "framer-motion"
import { Github, Linkedin, Mail, Send } from "lucide-react"
import { Button } from "@/components/ui/button"

export function FounderContact() {
  return (
    <section
      id="founder"
      className="border-t border-[rgba(100,130,200,0.1)] bg-site-surface py-20"
    >
      <div className="container mx-auto px-6">
        <div className="grid grid-cols-1 gap-12 md:grid-cols-2">
          {/* Founder */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6 }}
          >
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
              Founder
            </p>
            <h2 className="mb-5 text-2xl font-bold leading-tight tracking-tight text-site-text md:text-3xl">
              Who is building this.
            </h2>

            <div className="rounded-2xl border border-[rgba(100,130,200,0.12)] bg-site-card p-6">
              <p className="mb-1 text-base font-bold text-site-text">Evgeny Shokk</p>
              <p className="mb-4 text-sm font-medium text-site-accent">
                Founder &amp; Lead Engineer — AxiOMSphere
              </p>
              <p className="mb-3 text-sm leading-relaxed text-site-muted">
                Industrial engineer and AI developer with direct experience in asset integrity
                management system development for major capital projects. Building AxiOMSphere to
                close the gap between published AIMS standards and the structured, evidence-based
                work products that industrial projects need at the front end — where early decisions
                shape the entire operating organisation.
              </p>
              <p className="text-sm leading-relaxed text-site-muted">
                AxiOMSphere is a focused technical project: no external funding, no team beyond the
                founder. The goal is a validated, evidence-based development trajectory — from
                current M1 applied capability toward a governed platform that can support the full
                AIMS project lifecycle.
              </p>
            </div>
          </motion.div>

          {/* Contact */}
          <motion.div
            id="contact"
            initial={{ opacity: 0, x: 20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.6, delay: 0.1 }}
          >
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
              Contact
            </p>
            <h2 className="mb-5 text-2xl font-bold leading-tight tracking-tight text-site-text md:text-3xl">
              Get in Touch
            </h2>

            <div className="rounded-2xl border border-[rgba(100,130,200,0.12)] bg-site-card p-6">
              <p className="mb-5 text-sm leading-relaxed text-site-muted">
                For startup-credit programme review, collaboration enquiries and application
                follow-up:
              </p>

              <Button asChild size="lg" className="mb-5 w-full sm:w-auto">
                <a href="mailto:hello@axiomsphereai.com">
                  <Mail size={16} />
                  hello@axiomsphereai.com
                </a>
              </Button>

              <div className="flex flex-wrap gap-3">
                <a
                  href="https://github.com/AxiOMSphereAssistanceAIMS/AxiOMSphere"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-lg border border-[rgba(100,130,200,0.18)] px-4 py-2 text-sm font-medium text-site-muted transition-colors hover:border-site-accent hover:text-site-text"
                >
                  <Github size={16} />
                  GitHub
                </a>
                <a
                  href="https://www.linkedin.com/in/evgeny-shokk-54781716"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-lg border border-[rgba(100,130,200,0.18)] px-4 py-2 text-sm font-medium text-site-muted transition-colors hover:border-site-accent hover:text-site-text"
                >
                  <Linkedin size={16} />
                  LinkedIn
                </a>
                <a
                  href="https://t.me/AxiOMsphere_bot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-lg border border-[rgba(100,130,200,0.18)] px-4 py-2 text-sm font-medium text-site-muted transition-colors hover:border-site-accent hover:text-site-text"
                >
                  <Send size={16} />
                  Demo Bot
                </a>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  )
}
