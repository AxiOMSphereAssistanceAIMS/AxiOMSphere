import { motion } from "framer-motion"
import { Cpu, Brain, Database, ShieldCheck } from "lucide-react"
import { cn } from "@/lib/utils"

const CREDIT_CARDS = [
  {
    icon: <Brain size={20} />,
    title: "AI Capability Selection and Reliable Automation",
    desc: "Identify the AI capabilities best suited to specific AIMS tasks, prepare controlled tuning and evaluation programmes, assemble the required toolset, and develop reliable automated workflows that can detect failures, recover safely and improve through validated experience.",
  },
  {
    icon: <Cpu size={20} />,
    title: "Efficient server/GPU utilisation and optimized workload management",
    desc: "Evaluate how server and GPU capacity can be allocated effectively across development, validation and controlled model-improvement workloads: distributing tasks, reducing peak GPU demand, removing processing bottlenecks and increasing throughput without reducing engineering-support quality. This work will also help define the architecture and capacity requirements for a future dedicated compute cluster supporting controlled in-house development, evaluation and training of AxiOMSphere models.",
  },
  {
    icon: <Database size={20} />,
    title: "Project Knowledge and Continuous Improvement",
    desc: "Where authorised, process AIMS documents and related work products as they are prepared, reviewed and revised, helping improve their structure, clarity, completeness, consistency and alignment with approved requirements. Build controlled, master-aligned knowledge bases from developing and completed projects; identify and correct inherited inconsistencies; capture validated document improvements, failure history and lessons learned; and use this evidence to improve assistant skills, learning capability and operational recovery.",
  },
  {
    icon: <ShieldCheck size={20} />,
    title: "Security, Traceability and Information Reliability",
    desc: "Identify and reduce risks of data leakage, unauthorised requests and the circulation of unreliable documentation, while maintaining traceable evidence of system actions, validation results and responsible handling of authorised project information.",
  },
]

const cardVariants = {
  hidden: { opacity: 0, y: 18 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, delay: i * 0.09 },
  }),
}

export function Credits() {
  return (
    <section id="credits" className="py-20">
      <div className="container mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="mb-8"
        >
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-site-accent">
            Why Startup Credits Now
          </p>
          <p className="max-w-2xl text-base leading-relaxed text-site-muted">
            AxiOMSphere has established its current applied capability in on-demand AIMS document
            preparation and review. Startup credits are sought to validate this foundation at
            meaningful scale and to develop the next controlled capability layers: learning from
            validated engineering work, controlled issue correction and autonomous operational
            recovery, and coordinated execution across connected AxiOMSphere workflows. This
            programme is intended to build evidence for future engineer- and client-facing support
            during AIMS development and project readiness, without presenting planned capabilities
            as already operational.
          </p>
        </motion.div>

        {/* Credit cards */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {CREDIT_CARDS.map((card, i) => (
            <motion.div
              key={card.title}
              custom={i}
              variants={cardVariants}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true, margin: "-40px" }}
              className={cn(
                "flex flex-col gap-3 rounded-2xl border border-[rgba(100,130,200,0.12)] bg-site-card p-6",
                "transition-all duration-300 hover:border-[rgba(14,165,233,0.25)] hover:shadow-[0_0_20px_rgba(14,165,233,0.06)]",
              )}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[rgba(14,165,233,0.1)] text-site-accent">
                {card.icon}
              </div>
              <div>
                <h3 className="mb-1 text-sm font-semibold text-site-text">{card.title}</h3>
                <p className="text-sm leading-relaxed text-site-muted">{card.desc}</p>
              </div>
            </motion.div>
          ))}
        </div>

        {/* 90-day block */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="rounded-2xl border border-[rgba(14,165,233,0.2)] bg-[rgba(14,165,233,0.04)] p-6"
        >
          <h3 className="mb-3 text-base font-bold text-site-text">90-Day Validation Focus</h3>
          <p className="mb-3 text-sm leading-relaxed text-site-muted">
            Validate the current applied AIMS work-product workflow, generate measurable evidence
            of structure, traceability and specialist-review usefulness, and establish a controlled
            readiness recommendation for the next governed platform layer.
          </p>
          <p className="text-sm font-medium text-site-accent2">
            90-Day Validation Plan — available on request.
          </p>
        </motion.div>
      </div>
    </section>
  )
}
