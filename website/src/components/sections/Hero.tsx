import { motion } from "framer-motion"
import { BackgroundPaths } from "@/components/ui/background-paths"
import { Button } from "@/components/ui/button"

export function Hero() {
  return (
    <BackgroundPaths>
      <div className="relative z-10 container mx-auto px-6 py-28 text-center">
        {/* Eyebrow */}
        <motion.p
          className="mb-5 text-xs font-bold uppercase tracking-widest text-site-accent"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          AI assistant for Asset Integrity Management System development
        </motion.p>

        {/* H1 — letter-by-letter spring animation */}
        <H1Animated />

        {/* Lead paragraph */}
        <motion.p
          className="mx-auto mb-4 max-w-2xl text-base leading-relaxed text-[#adbac6] md:text-lg"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.5 }}
        >
          Industrial projects depend on decisions made during the establishment of the Asset
          Integrity Management System (AIMS), well before production begins. AxiOMSphere starts at
          the practical application level, helping specialists develop and validate interconnected
          AIMS work products in an assistant-guided and human-controlled environment — creating an
          integrated decision and document base for the future production management platform.
        </motion.p>

        {/* Audience statement */}
        <motion.p
          className="mx-auto mb-8 max-w-xl text-sm italic text-[#748498]"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.65 }}
        >
          For industrial project teams and engineers establishing Asset Integrity Management Systems
          (AIMS) before production begins.
        </motion.p>

        {/* CTAs */}
        <motion.div
          className="mb-6 flex flex-wrap items-center justify-center gap-3"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.82 }}
        >
          <Button size="lg" asChild>
            <a href="#demo">See the Demo</a>
          </Button>
          <Button size="lg" variant="outline" asChild>
            <a href="#credits">Startup Credits</a>
          </Button>
          <Button size="lg" variant="ghost" asChild>
            <a href="https://t.me/AxiOMsphere_bot" target="_blank" rel="noopener noreferrer">
              Try Demo Bot
            </a>
          </Button>
        </motion.div>

        {/* Status line */}
        <motion.p
          className="text-xs text-[#748498]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 1.05 }}
        >
          Current applied stage: AIMS work-product development and review &middot; Seeking startup
          credits for controlled validation
        </motion.p>
      </div>
    </BackgroundPaths>
  )
}

function H1Animated() {
  const text = "Establish an operational foundation before early decisions lead to costly rework."
  const words = text.split(" ")

  return (
    <motion.h1
      className="mx-auto mb-6 max-w-3xl text-3xl font-bold leading-tight tracking-tight text-site-text md:text-4xl lg:text-5xl"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.1 }}
    >
      {words.map((word, wi) => (
        <span key={wi} className="mr-[0.3em] inline-block last:mr-0">
          {word.split("").map((char, ci) => (
            <motion.span
              key={`${wi}-${ci}`}
              className="inline-block"
              initial={{ y: 14, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{
                delay: 0.15 + wi * 0.06 + ci * 0.018,
                type: "spring",
                stiffness: 160,
                damping: 22,
              }}
            >
              {char}
            </motion.span>
          ))}
        </span>
      ))}
    </motion.h1>
  )
}
