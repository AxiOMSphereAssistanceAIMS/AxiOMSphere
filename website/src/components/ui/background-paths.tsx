import { motion } from "framer-motion"

function FloatingPaths({ position }: { position: number }) {
  const paths = Array.from({ length: 36 }, (_, i) => ({
    id: i,
    d: `M-${380 - i * 5 * position} -${189 + i * 6}C-${380 - i * 5 * position} -${189 + i * 6} -${312 - i * 5 * position} ${216 - i * 6} ${152 - i * 5 * position} ${343 - i * 6}C${616 - i * 5 * position} ${470 - i * 6} ${684 - i * 5 * position} ${875 - i * 6} ${684 - i * 5 * position} ${875 - i * 6}`,
    color: `rgba(14,165,233,${0.04 + i * 0.018})`,
    width: 0.5 + i * 0.03,
  }))

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
      <svg
        className="w-full h-full"
        viewBox="0 0 696 316"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
      >
        <title>Decorative background paths</title>
        {paths.map((path) => (
          <motion.path
            key={path.id}
            d={path.d}
            stroke={path.color}
            strokeWidth={path.width}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{
              pathLength: 1,
              opacity: [0, 1, 1, 0],
            }}
            transition={{
              pathLength: { duration: 2.5, delay: path.id * 0.04, ease: "easeOut" },
              opacity: {
                duration: 5,
                delay: path.id * 0.04,
                times: [0, 0.24, 0.65, 1],
                ease: "easeInOut",
              },
            }}
          />
        ))}
      </svg>
    </div>
  )
}

interface BackgroundPathsProps {
  title?: string
  children?: React.ReactNode
}

export function BackgroundPaths({ title = "Background Paths", children }: BackgroundPathsProps) {
  const words = title.split(" ")

  return (
    <div className="relative w-full flex items-center justify-center overflow-hidden bg-site-bg">
      {/* Animated path layers */}
      <div className="absolute inset-0">
        <FloatingPaths position={1} />
        <FloatingPaths position={-1} />
      </div>

      {/* Radial glow overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "radial-gradient(ellipse 80% 60% at 50% 40%, rgba(14,165,233,0.07) 0%, transparent 65%)",
        }}
      />

      {/* Hero text */}
      {children == null ? (
        <div className="relative z-10 container mx-auto px-6 text-center py-20">
          <motion.h1
            className="text-3xl md:text-4xl lg:text-5xl font-bold tracking-tight text-site-text"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 1 }}
          >
            {words.map((word, wordIndex) => (
              <span key={wordIndex} className="inline-block mr-[0.35em] last:mr-0">
                {word.split("").map((letter, letterIndex) => (
                  <motion.span
                    key={`${wordIndex}-${letterIndex}`}
                    initial={{ y: 12, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{
                      delay: wordIndex * 0.08 + letterIndex * 0.025,
                      type: "spring",
                      stiffness: 160,
                      damping: 22,
                    }}
                    className="inline-block"
                  >
                    {letter}
                  </motion.span>
                ))}
              </span>
            ))}
          </motion.h1>
        </div>
      ) : (
        children
      )}
    </div>
  )
}
