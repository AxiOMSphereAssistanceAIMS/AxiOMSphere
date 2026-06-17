"""
DOCSREG Test Fixtures — Realistic >1200-char document samples.

Each fixture returns substantive, domain-appropriate content for testing
auditor acceptance and quality scoring with proper document_text inputs.
"""


def procedure_sample() -> str:
    """
    ISO 55001 maintenance procedure example (≥1200 chars).

    Realistic procedure for asset maintenance operations in industrial setting.
    """
    return """PREVENTIVE MAINTENANCE PROCEDURE FOR ASSET CLASS A-500 CENTRIFUGAL PUMPS

1. SCOPE AND PURPOSE
This procedure defines the preventive maintenance (PM) schedule for all Class A-500 centrifugal pumps deployed in the Primary Production Line. The objective is to maintain operational reliability at ≥99.5% uptime, detect early failure indicators, and ensure compliance with ISO 55001 asset integrity requirements. This procedure applies to pumps in service from commissioning date through end-of-life disposition.

2. MAINTENANCE SCHEDULE
2.1 Daily Inspection (performed by Operations personnel)
- Visual inspection for leaks around shaft seal and bearing housings
- Check discharge pressure reading; record if deviation >5% from baseline
- Listen for abnormal noise (cavitation, bearing wear, impeller imbalance)
- Record observations in equipment log

2.2 Monthly Service (performed by Maintenance Technician, 4 hours)
- Drain and inspect seal flush plan fluid for discoloration or contamination
- Replace motor bearing grease (specify ISO VG 68, lithium complex)
- Verify motor vibration <0.15 inches/second (0–10kHz band)
- Torque all suction/discharge flange bolts to specification (per pump datasheet)
- Inspect coupling alignment; adjust if offset >0.05 inches
- Replace inlet strainer basket if pressure drop >0.8 bar at nominal flow

2.3 Quarterly Overhaul (performed by Senior Technician + Maintenance Engineer, 16 hours)
- Full shaft runout check; replace bearings if radial runout >0.002 inches
- Disassemble and inspect pump internals (impeller, casing, vanes)
- Replace mechanical seal if wear pattern indicates <1,000 hours remaining service life
- Perform full flow performance curve verification; document against OEM baseline
- Inspect and replace suction/discharge piping supports; check for corrosion or fatigue cracks

2.4 Annual Certification (performed by Maintenance Engineer + OEM Representative, 32 hours)
- Full non-destructive testing (UT wall thickness on casing, MT surface inspection)
- Hydrostatic pressure test to 1.5× max operating pressure
- Full electrical motor insulation resistance test (megohm reading recorded)
- Centrifugal pump performance curve re-certification against ISO 9905 standard
- Update Asset Register with current condition state (GOOD/FAIR/POOR)

3. FAILURE RESPONSE PROTOCOL
If equipment fails unscheduled maintenance before next PM cycle, root cause analysis (RCA) is mandatory:
- Stop equipment; isolate from system via lockout/tagout
- Photograph failure mode; collect failed parts for forensic analysis
- Document elapsed time since last successful PM; compare against historical fleet data
- If failure rate exceeds 2× fleet average, escalate for accelerated inspection cycle
- Update PM schedule if systemic improvement opportunity identified

4. SPARE PARTS INVENTORY REQUIREMENT
Maintain minimum stock: 2× complete mechanical seal kits, 1× bearing set, 1× impeller (same model year), inlet strainer baskets (qty 3).

5. TRAINING AND COMPETENCY
All personnel executing PM steps must complete annual ISO 55001 Asset Integrity training + pump-specific hands-on certification (40 hours initial, 8 hours annual refresher).

6. DOCUMENT REVISION AND APPROVAL
Document Version: 3.2 | Last Revised: 2026-06-01 | Next Review: 2027-06-01 | Approved By: Asset Integrity Engineering Manager
"""


def policy_sample() -> str:
    """
    Asset integrity policy example (≥1200 chars).

    Organization-level policy establishing governance framework and principles.
    """
    return """ASSET INTEGRITY AND MAINTENANCE POLICY

Policy No: AIM-2026-001 | Effective Date: 2026-01-15 | Classification: Internal

1. POLICY STATEMENT
This organization is committed to maintaining critical assets in a safe, reliable, and operationally efficient condition throughout their service life. Asset integrity is a core pillar of operational excellence, regulatory compliance, and stakeholder trust. This policy establishes the governance framework, roles, responsibilities, and resource allocation required to achieve and sustain asset integrity across all operational domains.

2. SCOPE
This policy applies to all capital assets with operational value exceeding USD 50,000, including but not limited to: mechanical rotating equipment (pumps, compressors, fans), heat transfer equipment (exchangers, boilers, coolers), pressure vessels, piping systems, electrical generation and distribution infrastructure, and control systems. The policy applies equally to company-owned and leased assets used in production, quality assurance, research, and support functions.

3. CORE PRINCIPLES
3.1 Risk-Based Asset Management
Asset maintenance shall be prioritized according to risk impact (consequence of failure × probability of failure). Critical assets supporting revenue-generating functions shall receive preventive maintenance cycles not to exceed 80% of mean-time-between-failures (MTBF) for the asset class. Non-critical assets may operate on condition-based maintenance.

3.2 Reliability-Centered Maintenance (RCM)
All critical assets shall undergo formal RCM analysis at commissioning and at 5-year intervals thereafter. RCM analysis shall identify failure modes, consequences, and optimal maintenance strategy (preventive, predictive, reactive) for each asset.

3.3 Data-Driven Continuous Improvement
Performance data (uptime, failure history, maintenance cost, condition monitoring metrics) shall be collected, analyzed, and used to inform maintenance schedule optimization. Fleet-level trends shall be reviewed quarterly; individual asset performance reviewed monthly.

3.4 Competency and Training
Personnel responsible for asset maintenance shall demonstrate documented competency in their role through formal training, hands-on certification, and annual refresher training. Maintenance technicians and engineers shall maintain current certifications in ISO 55001 Asset Management and domain-specific technical skills.

4. GOVERNANCE STRUCTURE
4.1 Asset Integrity Steering Committee (quarterly meetings)
- Chief Operations Officer (Chair)
- Director of Maintenance & Reliability
- Director of Quality & Risk
- Finance Director (capital planning)
Responsibilities: Strategic oversight, capital allocation, policy update approval

4.2 Asset Integrity Operations Team (weekly meetings)
- Maintenance Engineering Manager (Chair)
- Maintenance Lead Technician
- Production Operations Manager
- Quality & Compliance Officer
Responsibilities: Operational execution, incident response, schedule adjustments

4.3 Individual Asset Custodians (asset owners)
Each business unit shall designate an Asset Custodian responsible for:
- Scheduling and execution of preventive maintenance
- Condition monitoring and trending
- Maintenance cost tracking and reporting
- Regulatory compliance verification

5. PERFORMANCE TARGETS
- Unplanned downtime due to preventive maintenance gaps: <2% annual availability loss
- Completion of scheduled preventive maintenance: ≥98% on schedule
- Mean time between failures (MTBF) for critical assets: ≥4,000 operating hours (increasing trajectory year-over-year)
- Maintenance cost as % of asset replacement value: 5–8% annually (target 6%)
- Regulatory audit findings related to asset integrity: zero critical findings

6. RESOURCE COMMITMENT
The organization shall allocate annual budget for asset maintenance equivalent to 6% of total asset replacement value. Budget shall include: spare parts inventory (minimum 3-month consumption), preventive maintenance labor (internal technician time), external service contracts (OEM field service, specialized inspections), training and certification, and condition monitoring technology and software.

7. COMPLIANCE AND MONITORING
Compliance with this policy shall be verified through quarterly management reviews. Non-compliance or repeated policy violations shall be escalated to the Steering Committee. External audits (regulatory, insurance, and third-party) shall be conducted annually to validate asset integrity practices.

8. POLICY REVIEW AND UPDATE
This policy shall be reviewed annually. Substantive updates require approval by the Asset Integrity Steering Committee. Policy versions and revision history shall be maintained in the Asset Management System.

Approved By: VP Operations | Policy Version: 1.0 | Last Updated: 2026-01-15 | Next Review: 2027-01-15
"""


def work_instruction_sample() -> str:
    """
    Step-by-step work instruction (≥1200 chars).

    Detailed procedural guidance for field technicians performing specific task.
    """
    return """WORK INSTRUCTION: BEARING REPLACEMENT FOR CLASS A-500 CENTRIFUGAL PUMP

Work Instruction No: WI-A500-BEARING-R01 | Revision: 2 | Effective: 2026-05-01

1. OBJECTIVE
Replace worn/damaged ball bearings in the Class A-500 centrifugal pump motor assembly. This work instruction ensures bearing replacement is performed safely, correctly, and reproducibly with minimal equipment downtime.

2. SAFETY PRECAUTIONS
- Do not attempt bearing replacement while equipment is running or energized.
- Lockout/tagout the motor circuit breaker per standard energy isolation procedure WI-LOTO-001.
- Verify isolation: attempt motor start using control panel; motor shall not start.
- Place warning tag: "MAINTENANCE IN PROGRESS — DO NOT OPERATE"
- Wear safety glasses and work gloves throughout procedure.
- Use proper lifting technique; bearing assemblies may weigh 15–25 lbs.
- Inspect work area for trip hazards; clear floor around equipment.

3. TOOLS AND MATERIALS REQUIRED
Tools:
- Socket set (metric 8–24 mm); torque wrench (0–100 Nm range)
- Bearing puller (hydraulic or mechanical, rated for 50 Nm load)
- Soft-faced mallet (copper or plastic)
- Feeler gauge set (to measure coupling alignment)
- Electric heating device for bearing thermal expansion (optional; recommended for tight-fit bearings)

Materials:
- Replacement bearing kit (model-specific, per motor nameplate; e.g., "FAG 6206-2Z" for motor size)
- Bearing grease (ISO VG 68, lithium complex; pre-packaged cartridge)
- Clean shop towels and absorbent materials

4. STEP-BY-STEP PROCEDURE

STEP 1: DOCUMENTATION
- Record bearing manufacturer name, part number, and current operating hours from equipment label.
- Photograph bearing location and current condition for failure analysis.
- Document ambient temperature (affects bearing expansion/contraction).

STEP 2: ACCESS PREPARATION
- Disconnect motor electrical connector (3-phase if applicable).
- Unbolt motor from pump flange (four M10 bolts; torque: 35 Nm).
- Carefully lift motor clear of pump; place on work bench with adequate support.
- If bearing housing is sealed/sealed, document seal configuration for reassembly.

STEP 3: BEARING REMOVAL
- Locate bearing retaining hardware: snap ring or lock nut (typically on non-drive end bearing).
- Using bearing puller, engage puller jaws under retaining ring or bearing outer race.
- Apply gradual pulling force (max 50 Nm); do NOT shock-load or hammer on puller.
- Once bearing breaks free, remove retaining hardware and lift bearing off motor shaft.
- Inspect motor shaft for corrosion, scoring, or damage; light surface rust is acceptable; deep scoring requires shaft replacement.

STEP 4: BEARING INSPECTION
- Examine removed bearing for failure mode: corrosion (water ingress), spalling (fatigue), discoloration (overheating), or contamination (foreign material).
- Record failure mode for root cause analysis; failure will be escalated to Asset Integrity team if bearing life was <2,000 hours.

STEP 5: SHAFT PREPARATION
- Clean motor shaft thoroughly with shop towel and degreaser.
- Dry completely; verify no moisture, dust, or debris remains.
- If tight-fit bearing is being installed and bearing cannot slide freely by hand, apply localized heat to bearing outer race (60–70°C) using heating pad or heat gun; verify with infrared thermometer.

STEP 6: NEW BEARING INSTALLATION
- Carefully slide new bearing onto motor shaft.
- If bearing requires push-fit (>5 mm interference), use soft-faced mallet with block of wood; strike gently and evenly; do NOT strike bearing directly.
- Reinstall retaining hardware (snap ring or lock nut); tighten lock nut to specified torque (per bearing kit documentation; typically 15–25 Nm).

STEP 7: BEARING LUBRICATION
- Pack bearing cavity with grease (approximately 1/3 full; over-greasing causes churning and heat).
- Use grease cartridge applicator to inject grease into bearing cavity.
- Rotate motor shaft by hand to distribute grease evenly; verify smooth rotation.

STEP 8: REASSEMBLY
- Position motor back onto pump flange with alignment within 0.05 inches (verify with feeler gauge).
- Install four M10 bolts; hand-tighten first.
- Using torque wrench, tighten bolts in diagonal cross pattern to 35 Nm.
- Reconnect motor electrical connector; verify three-phase connector is fully seated.

STEP 9: VERIFICATION
- Manually rotate pump shaft by hand (via pump coupling); rotation shall be smooth and free with no binding, grinding, or noise.
- Measure bearing temperature using infrared thermometer 30 seconds after manual rotation; temperature shall be ≤5°C above ambient.

STEP 10: DOCUMENTATION AND SIGN-OFF
- Update equipment maintenance log: date, bearing part number, technician name, time spent (approximately 1.5 hours)
- Photograph final assembly for record
- Remove lockout/tagout tag and restore motor to service
- Notify production that equipment is cleared for restart

5. QUALITY ASSURANCE CHECKPOINTS
After Step 3 (bearing removal): Inspect shaft for damage; if scoring present, STOP and escalate to Maintenance Engineer.
After Step 9 (verification): If rotation is not smooth or temperature >5°C above ambient, STOP and verify bearing installation; do not place in service.

6. NOTES AND TROUBLESHOOTING
- If bearing does not slide off shaft easily: apply penetrating oil and wait 15 minutes; repeat gentle mallet strikes.
- If new bearing does not slide onto shaft: confirm you have correct bearing model (verify part number matches motor nameplate); if mismatch, contact Maintenance Engineer.
- If bearing runs hot after restart (temperature >15°C above ambient), stop equipment immediately; likely causes are over-greasing or incorrect bearing installation; inspect and correct.

7. TRAINING REQUIREMENT
Only personnel certified in motor maintenance (annual certification from Maintenance Training Program) are authorized to perform this work instruction.

Prepared By: Senior Maintenance Technician | Reviewed By: Maintenance Engineering Manager | Approval Date: 2026-05-01
"""


def standard_requirement_sample() -> str:
    """
    Technical standard clause (≥1200 chars).

    Extract from industrial standard or technical specification document.
    """
    return """ISO 55001:2014 TECHNICAL REQUIREMENT EXCERPT — ASSET MANAGEMENT SYSTEM

4.4 OPERATION AND MAINTENANCE

4.4.1 Operational Planning
The organization shall establish and maintain documented procedures for the safe, efficient, and reliable operation of assets. These procedures shall address:
a) Normal operating parameters and acceptable operating envelopes (e.g., pressure, temperature, flow rate);
b) Start-up and shutdown sequences with embedded safety interlocks;
c) Operator roles, responsibilities, and required competencies;
d) Emergency response procedures and escalation triggers;
e) Monitoring and recording of operational parameters for trending and anomaly detection.

4.4.2 Preventive Maintenance Strategy Selection
Based on failure mode analysis (FMEA) or reliability-centered maintenance (RCM) analysis, the organization shall define maintenance strategies for each critical asset:
a) Time-based preventive maintenance: scheduled at fixed calendar or operating-hour intervals (e.g., "replace filter every 500 hours");
b) Condition-based maintenance: performed when asset condition deteriorates to predefined threshold (e.g., "replace bearing when vibration exceeds 0.20 in/s");
c) Predictive maintenance: decision to perform maintenance based on analysis of condition-monitoring data using statistical or AI-driven algorithms;
d) Reactive maintenance: corrective action following asset failure (acceptable only for non-critical assets with low consequence of failure).

For critical assets with high consequence of failure, time-based preventive maintenance shall be implemented with intervals not exceeding 80% of mean-time-between-failures (MTBF) for the asset class. The organization shall maintain documented justification for any deviation from this principle.

4.4.3 Maintenance Task Specification
Each maintenance task shall be fully documented with:
a) Work instruction with step-by-step guidance, safety precautions, and tools/materials required;
b) Expected duration (labor hours);
c) Qualification and certification requirements for technician performing work;
d) Acceptance criteria for successful completion (e.g., bearing temperature must return to baseline within 30 minutes);
e) Post-maintenance verification and testing procedure;
f) Spare parts bill-of-materials;
g) Risk assessment for task execution (environmental, personnel, equipment safety).

4.4.4 Maintenance Performance Targets
The organization shall establish quantitative performance targets for each asset or asset class:
a) Planned maintenance schedule compliance: percentage of scheduled PM tasks completed on or before target date;
b) Unplanned downtime: maximum acceptable annual downtime due to maintenance backlog, parts shortage, or technician unavailability;
c) Mean time between failures (MTBF): target MTBF for asset class, with annual improvement trajectory;
d) Maintenance cost efficiency: maintenance spend as percentage of asset replacement value (typically 5–10% annually);
e) Technician productivity: planned maintenance hours per asset per year (used to resource-load maintenance team).

4.4.5 Spare Parts Inventory Management
The organization shall maintain spare parts inventory for critical assets:
a) Identify critical spare parts: items whose absence delays maintenance completion by >2 hours (e.g., bearings, seals, impellers);
b) Establish minimum inventory levels: sufficient to cover expected consumption between replenishment cycles (minimum 2–3 months of normal consumption);
c) Inventory record accuracy: perform quarterly physical inventory audit; discrepancies >2% shall trigger investigation;
d) Shelf life management: monitor spare parts for age/deterioration; replace items exceeding shelf life or manufacturer storage recommendations;
e) Supplier performance: track on-time delivery and defect rates for critical spare parts suppliers.

4.4.6 Maintenance Resource Management
The organization shall allocate resources sufficient to execute planned maintenance:
a) Staffing: permanent maintenance technician headcount and skill distribution (preventive vs. corrective vs. specialized skills) shall be planned to accommodate average maintenance demand ±20% seasonal variation;
b) Contractor support: when internal capacity is insufficient, maintenance contractor hours shall be budgeted and performance monitored;
c) Capital budget: annual maintenance capital budget shall be ≥6% of asset replacement value; budget shall be allocated as: 60% labor, 20% spare parts, 15% external services (OEM field service, specialized testing), 5% training;
d) Tool and equipment: maintenance shop shall be equipped with tools and test equipment appropriate for asset classes in operation; tool calibration shall be verified annually.

4.4.7 Maintenance Effectiveness Monitoring
The organization shall monitor maintenance effectiveness through:
a) Maintenance cost tracking: actual spend versus budget; cost trends analyzed quarterly;
b) Equipment reliability metrics: uptime percentage, failure frequency, mean-time-between-failures trended annually;
c) Maintenance task compliance: percentage of PM tasks completed within planned date window;
d) Schedule effectiveness: for condition-based or predictive maintenance, rate of false positive alerts (unnecessary maintenance) and false negatives (failures between planned maintenance) shall be analyzed;
e) Corrective actions: root cause analysis (RCA) shall be performed for failures occurring <50% of planned MTBF; corrective actions tracked to closure.

4.4.8 Continuous Improvement
Results of maintenance monitoring shall be reviewed quarterly by the Asset Management team. Identified improvement opportunities shall be prioritized by impact (expected MTBF improvement, cost savings) and feasibility. Approved improvements shall be implemented through documented maintenance procedure revisions or RCM re-analysis.
"""


def compliance_checklist_sample() -> str:
    """
    Audit checklist (≥1200 chars).

    Structured checklist used for compliance verification and audit purposes.
    """
    return """ASSET INTEGRITY COMPLIANCE AUDIT CHECKLIST — ISO 55001:2014

Audit Date: __________ | Auditor Name: __________________ | Asset Type: _______________ | Equipment ID: __________

SECTION 1: DOCUMENTATION AND PROCEDURES
☐ 1.1 Preventive maintenance procedures documented for this asset class (yes/no; if no, document finding)
☐ 1.2 Maintenance procedure is current version and dated within last 12 months (yes/no)
☐ 1.3 Procedure includes: safety precautions (yes/no), tools/materials list (yes/no), step-by-step work instruction (yes/no), acceptance criteria (yes/no)
☐ 1.4 Work instructions include required technician qualifications/certifications (yes/no)
☐ 1.5 Documentation is accessible to field technicians (electronic system, laminated card at equipment, or printed manual; specify: ________)

SECTION 2: MAINTENANCE SCHEDULE COMPLIANCE
☐ 2.1 Preventive maintenance schedule established for this asset (yes/no; if yes, record interval: ________ hours or ________ days)
☐ 2.2 Last scheduled maintenance completed on: __________ (date); planned next maintenance: __________ (date)
☐ 2.3 Maintenance schedule is achievable based on staffing and spare parts availability (yes/no; if no, document constraint: __________)
☐ 2.4 Equipment maintenance log reviewed; last 3 maintenance events documented (yes/no; if no, missing records from: __________)
☐ 2.5 Unplanned repairs in past 12 months: __________ (count); for each, document whether RCA was performed (yes/no for each)

SECTION 3: MAINTENANCE EXECUTION QUALITY
☐ 3.1 Maintenance technician performing work holds current certification (training date: __________; valid until: __________)
☐ 3.2 Maintenance task completed with zero safety incidents (yes/no; if no, describe: __________)
☐ 3.3 Parts replaced are OEM-approved spares matching equipment specification (verify part numbers: __________)
☐ 3.4 Post-maintenance verification performed: equipment tested for smooth operation, normal temperature, and normal noise (yes/no)
☐ 3.5 Maintenance task completed within planned duration (planned: __________ hrs; actual: __________ hrs; variance <±20%: yes/no)

SECTION 4: SPARE PARTS INVENTORY
☐ 4.1 Critical spare parts identified for this asset class (list: __________)
☐ 4.2 Minimum inventory levels established (yes/no); current stock levels meet minimum (yes/no/partial; specify shortage: __________)
☐ 4.3 Spare parts are within shelf life; no evidence of deterioration (yes/no; if no, list expired items: __________)
☐ 4.4 Spare parts storage area is clean, dry, and protected from contamination (yes/no; if no, observations: __________)
☐ 4.5 Inventory records match physical stock count (yes/no; discrepancies >2%: yes/no; list: __________)

SECTION 5: CONDITION MONITORING AND TRENDING
☐ 5.1 Condition monitoring performed for this asset (vibration, temperature, noise, oil analysis, or other; specify: __________)
☐ 5.2 Baseline values established for normal operating condition (yes/no; baseline values: __________)
☐ 5.3 Recent monitoring data reviewed (past 3 months); trending shows stable or improving condition (yes/no; if degrading, describe: __________)
☐ 5.4 Alert thresholds defined; if threshold exceeded, escalation procedure initiated (yes/no; recent alerts: __________)
☐ 5.5 Monitoring data retained for ≥2 years (yes/no; oldest record date: __________)

SECTION 6: ROOT CAUSE ANALYSIS (RCA) FOR FAILURES
☐ 6.1 Any unplanned equipment failures in past 12 months (yes/no; count: __________)
☐ 6.2 For each failure, RCA performed within 5 business days (yes/no; if no, explain delay: __________)
☐ 6.3 RCA documents: failure symptom (yes/no), immediate cause (yes/no), root cause (yes/no), corrective action (yes/no)
☐ 6.4 Corrective actions implemented and verified effective (yes/no; if not implemented, reason: __________)
☐ 6.5 Maintenance procedure updated based on lessons learned from failures (yes/no; if yes, document change: __________)

SECTION 7: RESOURCE AND BUDGET ADEQUACY
☐ 7.1 Maintenance staffing adequate to execute planned PM schedule (yes/no; if no, staffing gap: __________ hrs/month)
☐ 7.2 Annual maintenance budget allocated (yes/no; amount: $ __________; % of asset replacement value: __________)
☐ 7.3 Budget spent year-to-date ($ __________); on pace to meet target (yes/no)
☐ 7.4 Maintenance tools and test equipment present and calibrated (yes/no; calibration date: __________)
☐ 7.5 External contractor or OEM field service available when needed (yes/no; response time guarantee: __________ days)

SECTION 8: REGULATORY AND COMPLIANCE REQUIREMENTS
☐ 8.1 Asset subject to regulatory inspection or compliance audit (yes/no; specify regulation: __________)
☐ 8.2 Last regulatory inspection/audit conducted: __________ (date); findings: __________ (count of findings)
☐ 8.3 Corrective actions from regulatory findings closed (yes/no; if open, list: __________)
☐ 8.4 Asset compliant with current ISO 55001 requirements (yes/no; if not, gap: __________)

SUMMARY FINDINGS
Non-Conformance Count (critical): __________
Non-Conformance Count (major): __________
Non-Conformance Count (minor): __________
Overall Compliance Rating: ☐ Full Compliance ☐ Substantial Compliance ☐ Non-Compliant

Risk Assessment: If equipment fails before next scheduled maintenance, estimated consequence: ☐ Negligible ☐ Minor ☐ Major ☐ Critical

Recommended Actions: ________________________________________________________________________

Auditor Signature: ________________________________ Date: __________

Reviewed By: ________________________________ (Maintenance Manager) Date: __________
"""


if __name__ == "__main__":
    # Quick validation: ensure all fixtures return >1200 chars
    fixtures = {
        "procedure_sample": procedure_sample(),
        "policy_sample": policy_sample(),
        "work_instruction_sample": work_instruction_sample(),
        "standard_requirement_sample": standard_requirement_sample(),
        "compliance_checklist_sample": compliance_checklist_sample(),
    }

    for name, content in fixtures.items():
        length = len(content)
        status = "✓" if length >= 1200 else "✗"
        print(f"{status} {name}: {length} chars")
