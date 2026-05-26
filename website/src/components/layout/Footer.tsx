import { Github, Linkedin, Mail } from "lucide-react"

export function Footer() {
  return (
    <footer className="border-t border-[rgba(100,130,200,0.1)] bg-site-bg">
      <div className="container mx-auto px-6 py-12">
        <div className="flex flex-col items-center gap-6 md:flex-row md:justify-between">
          {/* Brand */}
          <div className="flex flex-col items-center gap-1 md:items-start">
            <span className="text-base font-bold text-site-text">
              Axi<span className="text-site-accent">OM</span>Sphere
            </span>
            <span className="text-xs text-site-subtle">
              Privacy-first industrial AI · AIMS work-product development
            </span>
          </div>

          {/* Links */}
          <div className="flex items-center gap-4">
            <a
              href="https://github.com/AxiOMSphereAssistanceAIMS/AxiOMSphere"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="GitHub repository"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-site-muted transition-colors hover:bg-[rgba(255,255,255,0.06)] hover:text-site-text"
            >
              <Github size={18} />
            </a>
            <a
              href="https://www.linkedin.com/in/evgeny-shokk-54781716"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="LinkedIn profile"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-site-muted transition-colors hover:bg-[rgba(255,255,255,0.06)] hover:text-site-text"
            >
              <Linkedin size={18} />
            </a>
            <a
              href="mailto:hello@axiomsphereai.com"
              aria-label="Send email"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-site-muted transition-colors hover:bg-[rgba(255,255,255,0.06)] hover:text-site-text"
            >
              <Mail size={18} />
            </a>
          </div>
        </div>

        <div className="mt-8 border-t border-[rgba(100,130,200,0.08)] pt-6 text-center">
          <p className="text-xs text-site-subtle">
            © 2026 AxiOMSphere · Development-stage product · All capabilities subject to validation and
            availability
          </p>
          <p className="mt-1 text-xs text-site-subtle/60">
            © 2026 AxiOMSphere. All rights reserved. AxiOMSphere and associated product materials are
            proprietary.
          </p>
        </div>
      </div>
    </footer>
  )
}
