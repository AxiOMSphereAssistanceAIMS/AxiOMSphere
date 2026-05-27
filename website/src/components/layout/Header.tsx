import { useState, useEffect } from "react"
import { Menu, X } from "lucide-react"
import { cn } from "@/lib/utils"


const NAV_LINKS = [
  { label: "Current Stage",  href: "#current-stage" },
  { label: "Demo",           href: "#demo" },
  { label: "Roadmap",        href: "#roadmap" },
  { label: "Credits",        href: "#credits" },
  { label: "Founder",        href: "#founder" },
  { label: "Contact",        href: "#contact" },
]

export function Header() {
  const [scrolled, setScrolled]   = useState(false)
  const [menuOpen, setMenuOpen]   = useState(false)

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 24)
    window.addEventListener("scroll", handler, { passive: true })
    return () => window.removeEventListener("scroll", handler)
  }, [])

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 transition-all duration-300",
        scrolled
          ? "border-b border-[rgba(100,130,200,0.1)] bg-[rgba(8,11,18,0.88)] backdrop-blur-md"
          : "bg-transparent",
      )}
    >
      <div className="container mx-auto flex h-16 items-center justify-between px-6">
        {/* Logo */}
        <a href="#" className="flex items-center gap-2.5 text-site-text no-underline hover:text-site-text">
          <img src="/logo.png" alt="AxiOMSphere logo" className="h-8 w-8 flex-shrink-0 rounded-lg" />
          <span className="text-lg font-bold tracking-tight">
            Axi<span className="text-site-accent">OM</span>Sphere
          </span>
        </a>

        {/* Desktop nav */}
        <nav className="hidden items-center gap-1 lg:flex" aria-label="Main navigation">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium text-site-muted transition-colors",
                "hover:bg-[rgba(255,255,255,0.04)] hover:text-site-text",
                "no-underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-site-accent",
              )}
            >
              {link.label}
            </a>
          ))}
        </nav>

        {/* Mobile menu toggle */}
        <button
          className="flex h-10 w-10 items-center justify-center rounded-lg text-site-muted transition-colors hover:bg-[rgba(255,255,255,0.06)] hover:text-site-text lg:hidden"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile nav drawer */}
      {menuOpen && (
        <div className="border-t border-[rgba(100,130,200,0.1)] bg-[rgba(8,11,18,0.96)] backdrop-blur-md lg:hidden">
          <nav className="container mx-auto flex flex-col gap-1 px-6 py-4" aria-label="Mobile navigation">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="rounded-md px-3 py-2.5 text-sm font-medium text-site-muted transition-colors hover:bg-[rgba(255,255,255,0.04)] hover:text-site-text no-underline"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </a>
            ))}
          </nav>
        </div>
      )}
    </header>
  )
}
