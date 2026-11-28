"""The legal reason of each regulatory pack: the subject relevance.py retains for it and the text it rests on, a table
for maintainers."""




# The subject retained for each regulatory pack and its legal reason. A regulation pattern is selected by a person
# who confirmed that the regulation applies to the organization; the subject then says which changes it reaches.
LEGAL_BASIS = {
    "gdpr": "personal or regulated data: the GDPR applies to the processing of personal data (Art. 2(1)). Within "
            "it, the rules about a new processing (record Art. 30, lawful basis Art. 6, retention Art. 5(1)(e), "
            "DPIA Art. 35, rights Art. 15 to 17, information Art. 13 and 14, consent to trackers ePrivacy Art. 5(3)) "
            "are left out of a bug or a maintenance, and those about a new "
            "processor (Art. 28) or a transfer outside the EEA (Chapter V) out of a bug only: a migration often "
            "changes where the data goes, a fix almost never.",
    "minors-data-protection": "personal or regulated data: GDPR Art. 8 and 35 and DSA Art. 28 apply to the "
                              "processing of children's data; the rules about a new flow are left out of a bug or a "
                              "maintenance.",
    "health-data-protection": "personal or regulated data: health data is a special category (GDPR Art. 9), and "
                              "software that processes it may be a medical device (Regulation (EU) 2017/745) or an "
                              "EHR system (Regulation (EU) 2025/327); the rules about a new processing are left out "
                              "of a bug or a maintenance.",
    "dora": "regulated data, infrastructure, or a feature or maintenance on a customer or service surface with "
            "personal data: for a financial entity, a change to an ICT system that serves clients or holds their "
            "data is a change of Art. 9(4)(e), its assets belong to the inventory of Art. 8, and a new ICT provider "
            "enters the register of Art. 28(3). A bug fix restores a system as it was and adds no asset or provider.",
    "nis2": "regulated data, infrastructure, or a feature or maintenance on a customer or service surface with "
            "personal data: the measures of Art. 21(2) cover the network and information systems an essential or "
            "important entity uses for its services, their suppliers (point d) included.",
    "aviation-information-security": "regulated data, or code, services and infrastructure: for an organisation listed "
                                     "in Art. 2 of Delegated Regulation (EU) 2022/1645 or Art. 2(1) of Implementing "
                                     "Regulation (EU) 2023/203, the systems, data and interfaces that support its "
                                     "activities belong to the risk assessment of IS.D.OR.205 or IS.I.OR.205.",
    "airborne-software-assurance": "code, services and infrastructure: AMC 20-115D applies to applicants, design "
                                   "approval holders and developers of airborne software (section 2), and the "
                                   "objectives of each software level are in the Annex A tables of ED-12C/DO-178C "
                                   "(section 6.a).",
    "airworthiness-security": "code, services and infrastructure: AMC 20-42 section 2 applies to manufacturers and "
                              "design approval holders, and its product information security risk assessment is an "
                              "acceptable means under Annex I (Part 21) to Regulation (EU) No 748/2012.",
    "european-accessibility-act": "a customer surface: Directive (EU) 2019/882 sets accessibility requirements for "
                                  "services provided to consumers (Art. 2(2), Annex I), applied since 28 June 2025.",
    "cyber-resilience-act": "infrastructure or credentials: its rules act on how releases are built, shipped and "
                            "updated and how vulnerabilities are handled (Annex I Part II, Art. 13(8)).",
    "incident-notification": "each row follows the pack of its regulation (GDPR Art. 33 and 34, NIS 2 Art. 23, DORA "
                             "Art. 19, CRA Art. 14, AI Act Art. 73) and is asked when that pack concerns the task; the "
                             "matrix itself also when the change touches infrastructure or credentials.",
    "eu-ai-act": "AI or decisions about people: the AI Act applies to AI systems (Art. 2), with the Art. 50 "
                 "transparency duties for systems that interact with people or generate content and Annex III for "
                 "systems that decide about people, such as in employment or credit.",
    "pci-dss": "regulated data, or money in a brief that names cards or payments: PCI DSS v4.0.1 applies to the "
               "system components that store, process or transmit cardholder data or can affect their security; "
               "prices, payroll or spending without a card are not in its scope.",
    "iso-27001": "regulated data, credentials, infrastructure, or personal data on a customer or service surface: "
                 "the Annex A controls protect the information in the scope of the management system, personal data "
                 "first (control 5.34).",
    "notice-and-action": "a task the trust and safety board reviews: DSA Art. 16, 17 and 20 apply to a hosting "
                         "service's notices, statements of reasons and complaints, and Regulation (EU) 2021/784 Art. 3 "
                         "to removal orders; the brief's words about reports, moderation or illegal content route "
                         "that board.",
    "pay-transparency": "pay or recruitment reviewed by the HR board, or software that decides about people: "
                        "Directive (EU) 2023/970 Art. 5 governs job postings and hiring forms, Art. 6 the pay "
                        "criteria and Art. 9 the pay gap report.",
    "insurance-distribution": "a customer surface with money or decisions about people: IDD Art. 20 and 25 govern "
                              "the sale and the approval of an insurance product, and AI Act Annex III point 5(c) "
                              "pricing for natural persons.",
    "online-consumer-sales": "a customer surface with money: Directive 2011/83/EU Art. 6 and 8 govern the "
                             "information and the order button of a distance sale to consumers.",
    "unece-r155": "the code of a service, a customer surface or infrastructure: UN Regulation No 155 asks the vehicle "
                  "manufacturer for a risk assessment, mitigations and tests of each vehicle type (paragraphs 7.3.3 "
                  "to 7.3.6, Annex 5) and for the monitoring of vehicles in use, and Regulation (EU) 2019/2144 Annex II "
                  "row D4 makes it a condition of EU type-approval.",
    "unece-r156": "the code of a service, a customer surface or infrastructure: UN Regulation No 156 asks the vehicle "
                  "manufacturer to identify software versions, assess the effect of each update on the type approval "
                  "and protect its delivery (paragraphs 7.1 and 7.2), where an approval authority applies it; "
                  "Regulation (EU) 2019/2144 does not list it in Annex I or Annex II.",
    "public-sector-accessibility": "the user interface: Directive (EU) 2016/2102 Art. 4 applies to the websites "
                                   "and mobile applications of public sector bodies.",
    "france-health-data-hosting": "personal or regulated data: Art. L1111-8 of the Code de la santé publique "
                                  "requires the host of personal health data to hold a certificate of conformity, "
                                  "and Art. R1111-9-1 and R1111-11 set the storage in the EU or EEA and the contract.",
    "france-rgaa-accessibility": "the user interface: Art. 47 of loi n° 2005-102 binds certain public and private "
                                 "entities to make their online public communication services accessible, tested "
                                 "with the RGAA.",
    "france-cookies-and-trackers": "the user interface: Art. 82 of loi n° 78-17 requires information and consent "
                                   "before trackers are written to or read from a user's device, unless exempt.",
    "france-public-sector-security": "regulated data, infrastructure, credentials, or personal data on a customer or "
                                     "service surface: Art. 3 and 4 of décret n° 2010-112 and Art. 4-3 of décret "
                                     "n° 2019-1088 hold a public authority to a risk analysis and a homologation.",
    "france-e-invoicing": "money: the DGFiP e-invoicing and e-reporting reform of impots.gouv.fr covers the invoices "
                          "and the transaction and payment data of businesses liable to French VAT.",
    "web-accessibility": "the user interface: WCAG 2.2, through EN 301 549, is the test of Directive (EU) 2016/2102 "
                         "and of the accessibility requirements a customer-facing screen meets.",
}
