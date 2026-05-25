import { Header } from "@/components/layout/Header"
import { Footer } from "@/components/layout/Footer"
import { Hero } from "@/components/sections/Hero"
import { WhatIs } from "@/components/sections/WhatIs"
import { Opportunity } from "@/components/sections/Opportunity"
import { Platform } from "@/components/sections/Platform"
import { CurrentStage } from "@/components/sections/CurrentStage"
import { Demo } from "@/components/sections/Demo"
import { Framework } from "@/components/sections/Framework"
import { Roadmap } from "@/components/sections/Roadmap"
import { Credits } from "@/components/sections/Credits"
import { Vision } from "@/components/sections/Vision"
import { Deployment } from "@/components/sections/Deployment"
import { FounderContact } from "@/components/sections/FounderContact"

export default function App() {
  return (
    <>
      <Header />
      <main>
        <Hero />
        <WhatIs />
        <Opportunity />
        <Platform />
        <CurrentStage />
        <Demo />
        <Framework />
        <Roadmap />
        <Credits />
        <Vision />
        <Deployment />
        <FounderContact />
      </main>
      <Footer />
    </>
  )
}
