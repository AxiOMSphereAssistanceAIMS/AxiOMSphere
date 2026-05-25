import { motion } from "framer-motion"
import { BookOpen, Network, BarChart2 } from "lucide-react"
import { BentoGrid, type BentoItem } from "@/components/ui/bento-grid"

const PLATFORM_ITEMS: BentoItem[] = [
  {
    title: "Project Knowledge",
    description:
      "Retain and retrieve approved project knowledge so specialists can understand what has already been created, reviewed and connected.",
    icon: <BookOpen size={20} />,
    status: "Applied",
  },
  {
    title: "Departmental Coordination",
    description:
      "Support future visibility of relationships between functions, interfaces and related work products as project requirements evolve.",
    icon: <Network size={20} />,
    status: "In Development",
  },
  {
    title: "Resource Decisions",
    description:
      "Build the basis for improved analysis of information required for functional planning, cost assessment and reduced duplication of effort.",
    icon: <BarChart2 size={20} />,
    status: "Planned",
  },
]

export function Platform() {
  return (
    <section
      id="platform"
      className="border-y border-[rgba(100,130,200,0.1)] bg-site-surface py-20"
    >
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mb-8"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            The Platform Potential
          </p>
          <p className="max-w-2xl text-base leading-relaxed text-site-muted">
            AxiOMSphere starts with the practical applied task of developing and reviewing connected
            AIMS work products. The broader objective is to build an industrial knowledge and
            coordination environment that can help specialists understand what has already been
            created for the project, use approved company knowledge, identify dependencies across
            parallel departmental functions and interfaces, consolidate and analyse required
            information, reduce duplicated effort and improve the use of specialist time and project
            resources.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.6, delay: 0.15 }}
        >
          <BentoGrid items={PLATFORM_ITEMS} />
        </motion.div>

        <motion.p
          className="mt-6 text-sm italic text-site-subtle"
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          Broader AIMS-guided project-development support is a long-term objective and depends on
          validated, responsibly governed capability layers.
        </motion.p>
      </div>
    </section>
  )
}
