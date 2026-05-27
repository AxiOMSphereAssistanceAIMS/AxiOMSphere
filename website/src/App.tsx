import { Header } from "@/components/layout/Header"
import { Footer } from "@/components/layout/Footer"
import { Hero } from "@/components/sections/Hero"
import { CapabilityCards } from "@/components/sections/capability-cards"
import { Demo } from "@/components/sections/Demo"
import { Roadmap } from "@/components/sections/Roadmap"
import { CurrentStage } from "@/components/sections/CurrentStage"
import { Framework } from "@/components/sections/Framework"
import { Credits } from "@/components/sections/Credits"
import { FounderContact } from "@/components/sections/FounderContact"

export default function App() {
  return (
    <>
      <Header />
      <main>
        <Hero />
        <CapabilityCards />
        <Demo />
        <Roadmap />
        <CurrentStage />
        <Framework />
        <Credits />
        <FounderContact />
      </main>
      <Footer />
    </>
  )
}
