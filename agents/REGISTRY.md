# Agent Registry — Octopus Interdisciplinary Team

> Auto-activates agents as subagents when the brain detects matching context.
> Manual activation: "Activate [Agent Name] for this task"
> Agents complement skills — agent = who (role/persona), skill = how (technique), arm = for whom (client).

## Activation Protocol

### Automatic (Brain-Triggered)
The brain reads this registry and activates the best-fit agent when:
1. A task matches an agent's trigger keywords
2. The agent's expertise is needed for the current arm's work
3. Multi-step work requires specialist handoff

### Manual
Say: "Activate [Agent Name]" or "Use [Agent Name] mode"

### Combined with Skills
Agents load their persona + the relevant skills for the active arm. Example:
- Brain activates **Database Optimizer** agent
- Agent loads `explain-analyze-validation` + `index-creation-concurrently` skills from a client arm
- Result: specialist persona + client-specific techniques

---

## Agent Divisions

### Academic

| Agent | File | Triggers |
|-------|------|----------|
| 🌍 Anthropologist | [academic/academic-anthropologist.md](academic/academic-anthropologist.md) | cultural systems, ethnographic, rituals, kinship, belief |
| 🗺️ Geographer | [academic/academic-geographer.md](academic/academic-geographer.md) | geography, cartography, spatial analysis, climate, terrain |
| 📚 Historian | [academic/academic-historian.md](academic/academic-historian.md) | historical analysis, periodization, historiography, primary sources |
| 📜 Narratologist | [academic/academic-narratologist.md](academic/academic-narratologist.md) | narrative theory, story structure, character arcs, literary analysis |
| 🧠 Psychologist | [academic/academic-psychologist.md](academic/academic-psychologist.md) | behavior, personality, motivation, cognitive patterns, clinical |

### Design

| Agent | File | Triggers |
|-------|------|----------|
| 🎨 Brand Guardian | [design/design-brand-guardian.md](design/design-brand-guardian.md) | brand identity, consistency, positioning, style guide |
| 📷 Image Prompt Engineer | [design/design-image-prompt-engineer.md](design/design-image-prompt-engineer.md) | AI image generation, photography prompts, visual concepts |
| 🌈 Inclusive Visuals Specialist | [design/design-inclusive-visuals-specialist.md](design/design-inclusive-visuals-specialist.md) | representation, AI bias, cultural accuracy, affirming imagery |
| 🎨 UI Designer | [design/design-ui-designer.md](design/design-ui-designer.md) | visual design, component library, interface, pixel-perfect, accessibility |
| 📐 UX Architect | [design/design-ux-architect.md](design/design-ux-architect.md) | CSS systems, technical architecture, implementation guidance, foundations |
| 🔬 UX Researcher | [design/design-ux-researcher.md](design/design-ux-researcher.md) | user behavior, usability testing, design insights, user satisfaction |
| 🎬 Visual Storyteller | [design/design-visual-storyteller.md](design/design-visual-storyteller.md) | visual narratives, multimedia, brand storytelling, emotional engagement |
| ✨ Whimsy Injector | [design/design-whimsy-injector.md](design/design-whimsy-injector.md) | personality, delight, playful elements, whimsy, memorable interactions |

### Engineering

| Agent | File | Triggers |
|-------|------|----------|
| 🧬 AI Data Remediation Engineer | [engineering/engineering-ai-data-remediation-engineer.md](engineering/engineering-ai-data-remediation-engineer.md) | data anomalies, self-healing pipelines, data quality, SLM remediation |
| 🤖 AI Engineer | [engineering/engineering-ai-engineer.md](engineering/engineering-ai-engineer.md) | machine learning, model deployment, AI features, ML pipelines |
| ⚡ Autonomous Optimization Architect | [engineering/engineering-autonomous-optimization-architect.md](engineering/engineering-autonomous-optimization-architect.md) | API performance, cost guardrails, shadow-testing, optimization |
| 🏗️ Backend Architect | [engineering/engineering-backend-architect.md](engineering/engineering-backend-architect.md) | system design, database architecture, API development, cloud infrastructure |
| 🧱 CMS Developer | [engineering/engineering-cms-developer.md](engineering/engineering-cms-developer.md) | Drupal, WordPress, theme development, plugins, CMS |
| 👁️ Code Reviewer | [engineering/engineering-code-reviewer.md](engineering/engineering-code-reviewer.md) | code review, correctness, maintainability, security, performance |
| 🔧 Data Engineer | [engineering/engineering-data-engineer.md](engineering/engineering-data-engineer.md) | data pipelines, ETL, lakehouse, Spark, dbt, streaming |
| 🗄️ Database Optimizer | [engineering/engineering-database-optimizer.md](engineering/engineering-database-optimizer.md) | schema design, query optimization, indexing, PostgreSQL, performance tuning |
| ⚙️ DevOps Automator | [engineering/engineering-devops-automator.md](engineering/engineering-devops-automator.md) | infrastructure automation, CI/CD, cloud operations, deployment |
| 📧 Email Intelligence Engineer | [engineering/engineering-email-intelligence-engineer.md](engineering/engineering-email-intelligence-engineer.md) | email parsing, MIME, structured extraction, AI agents |
| 🔩 Embedded Firmware Engineer | [engineering/engineering-embedded-firmware-engineer.md](engineering/engineering-embedded-firmware-engineer.md) | ESP32, RTOS, ARM Cortex-M, firmware, bare-metal |
| 🔗 Feishu Integration Developer | [engineering/engineering-feishu-integration-developer.md](engineering/engineering-feishu-integration-developer.md) | Feishu, Lark, bots, Bitable, workflow automation |
| 🔧 Filament Optimization Specialist | [engineering/engineering-filament-optimization-specialist.md](engineering/engineering-filament-optimization-specialist.md) | Filament PHP, admin interfaces, restructuring, usability |
| 🖥️ Frontend Developer | [engineering/engineering-frontend-developer.md](engineering/engineering-frontend-developer.md) | React, Vue, Angular, web technologies, UI implementation |
| 🌿 Git Workflow Master | [engineering/engineering-git-workflow-master.md](engineering/engineering-git-workflow-master.md) | git, branching strategies, conventional commits, version control |
| 🚨 Incident Response Commander | [engineering/engineering-incident-response-commander.md](engineering/engineering-incident-response-commander.md) | incident management, post-mortem, SLO/SLI, on-call |
| 📲 Mobile App Builder | [engineering/engineering-mobile-app-builder.md](engineering/engineering-mobile-app-builder.md) | iOS, Android, mobile development, cross-platform |
| ⚡ Rapid Prototyper | [engineering/engineering-rapid-prototyper.md](engineering/engineering-rapid-prototyper.md) | prototype, MVP, proof-of-concept, rapid development |
| 🔒 Security Engineer | [engineering/engineering-security-engineer.md](engineering/engineering-security-engineer.md) | threat modeling, vulnerability assessment, secure code review, security architecture |
| 💎 Senior Developer | [engineering/engineering-senior-developer.md](engineering/engineering-senior-developer.md) | Laravel, Livewire, Three.js, advanced CSS, full-stack |
| 🏛️ Software Architect | [engineering/engineering-software-architect.md](engineering/engineering-software-architect.md) | system design, domain-driven design, architectural patterns, scalability |
| ⛓️ Solidity Smart Contract Engineer | [engineering/engineering-solidity-smart-contract-engineer.md](engineering/engineering-solidity-smart-contract-engineer.md) | Solidity, EVM, smart contracts, DeFi, gas optimization |
| 🛡️ SRE (Site Reliability Engineer) | [engineering/engineering-sre.md](engineering/engineering-sre.md) | SLOs, error budgets, observability, chaos engineering, toil reduction |
| 📚 Technical Writer | [engineering/engineering-technical-writer.md](engineering/engineering-technical-writer.md) | documentation, API references, README, tutorials |
| 🎯 Threat Detection Engineer | [engineering/engineering-threat-detection-engineer.md](engineering/engineering-threat-detection-engineer.md) | SIEM, MITRE ATT&CK, threat hunting, detection rules |
| 💬 WeChat Mini Program Developer | [engineering/engineering-wechat-mini-program-developer.md](engineering/engineering-wechat-mini-program-developer.md) | WeChat, Mini Programs, WXML/WXSS, payment systems |

### Game Development

| Agent | File | Triggers |
|-------|------|----------|
| 🧩 Blender Add-on Engineer | [game-development/blender/blender-addon-engineer.md](game-development/blender/blender-addon-engineer.md) | Blender, Python add-ons, DCC pipeline, asset validators |
| 🎵 Game Audio Engineer | [game-development/game-audio-engineer.md](game-development/game-audio-engineer.md) | FMOD, Wwise, spatial audio, adaptive music, audio budgeting |
| 🎮 Game Designer | [game-development/game-designer.md](game-development/game-designer.md) | GDD, player psychology, economy balancing, gameplay loops |
| 🎯 Godot Gameplay Scripter | [game-development/godot/godot-gameplay-scripter.md](game-development/godot/godot-gameplay-scripter.md) | GDScript, Godot 4, C# integration, node architecture, signals |
| 🌐 Godot Multiplayer Engineer | [game-development/godot/godot-multiplayer-engineer.md](game-development/godot/godot-multiplayer-engineer.md) | Godot networking, MultiplayerAPI, ENet, WebRTC, RPCs |
| 💎 Godot Shader Developer | [game-development/godot/godot-shader-developer.md](game-development/godot/godot-shader-developer.md) | Godot shading, VisualShader, post-processing, VFX |
| 🗺️ Level Designer | [game-development/level-designer.md](game-development/level-designer.md) | layout theory, pacing, encounter design, environmental narrative |
| 📖 Narrative Designer | [game-development/narrative-designer.md](game-development/narrative-designer.md) | branching dialogue, lore architecture, environmental storytelling |
| 👤 Roblox Avatar Creator | [game-development/roblox-studio/roblox-avatar-creator.md](game-development/roblox-studio/roblox-avatar-creator.md) | UGC, avatar rigging, Creator Marketplace, texture standards |
| 🎪 Roblox Experience Designer | [game-development/roblox-studio/roblox-experience-designer.md](game-development/roblox-studio/roblox-experience-designer.md) | engagement loops, monetization, DataStore, player retention |
| 🔧 Roblox Systems Scripter | [game-development/roblox-studio/roblox-systems-scripter.md](game-development/roblox-studio/roblox-systems-scripter.md) | Luau, RemoteEvents, client-server security, DataStore |
| 🎨 Technical Artist | [game-development/technical-artist.md](game-development/technical-artist.md) | shaders, VFX systems, LOD, art pipeline, asset optimization |
| 🏛️ Unity Architect | [game-development/unity/unity-architect.md](game-development/unity/unity-architect.md) | ScriptableObjects, decoupled systems, Unity modular design |
| 🛠️ Unity Editor Tool Developer | [game-development/unity/unity-editor-tool-developer.md](game-development/unity/unity-editor-tool-developer.md) | EditorWindows, PropertyDrawers, pipeline automation |
| 🔗 Unity Multiplayer Engineer | [game-development/unity/unity-multiplayer-engineer.md](game-development/unity/unity-multiplayer-engineer.md) | Netcode for GameObjects, Relay, Lobby, lag compensation |
| ✨ Unity Shader Graph Artist | [game-development/unity/unity-shader-graph-artist.md](game-development/unity/unity-shader-graph-artist.md) | Shader Graph, HLSL, URP/HDRP, render pipelines |
| 🌐 Unreal Multiplayer Architect | [game-development/unreal-engine/unreal-multiplayer-architect.md](game-development/unreal-engine/unreal-multiplayer-architect.md) | UE5 networking, Actor replication, server-authoritative, prediction |
| ⚙️ Unreal Systems Engineer | [game-development/unreal-engine/unreal-systems-engineer.md](game-development/unreal-engine/unreal-systems-engineer.md) | C++/Blueprint, Nanite, Lumen, Gameplay Ability System |
| 🎨 Unreal Technical Artist | [game-development/unreal-engine/unreal-technical-artist.md](game-development/unreal-engine/unreal-technical-artist.md) | Material Editor, Niagara VFX, PCG, UE5 art pipeline |
| 🌍 Unreal World Builder | [game-development/unreal-engine/unreal-world-builder.md](game-development/unreal-engine/unreal-world-builder.md) | World Partition, Landscape, procedural foliage, open-world |

### Marketing

| Agent | File | Triggers |
|-------|------|----------|
| 🔮 AI Citation Strategist | [marketing/marketing-ai-citation-strategist.md](marketing/marketing-ai-citation-strategist.md) | AEO, GEO, AI recommendations, brand visibility, ChatGPT citations |
| 📱 App Store Optimizer | [marketing/marketing-app-store-optimizer.md](marketing/marketing-app-store-optimizer.md) | ASO, app store, discoverability, conversion rate |
| 🇨🇳 Baidu SEO Specialist | [marketing/marketing-baidu-seo-specialist.md](marketing/marketing-baidu-seo-specialist.md) | Baidu, Chinese search, ICP compliance, China market |
| 🎬 Bilibili Content Strategist | [marketing/marketing-bilibili-content-strategist.md](marketing/marketing-bilibili-content-strategist.md) | Bilibili, B站, UP主, danmaku, community |
| 📘 Book Co-Author | [marketing/marketing-book-co-author.md](marketing/marketing-book-co-author.md) | thought leadership, book chapters, positioning, voice notes |
| 🎠 Carousel Growth Engine | [marketing/marketing-carousel-growth-engine.md](marketing/marketing-carousel-growth-engine.md) | TikTok carousel, Instagram carousel, viral, auto-publish |
| 🛒 China E-Commerce Operator | [marketing/marketing-china-ecommerce-operator.md](marketing/marketing-china-ecommerce-operator.md) | Taobao, Tmall, Pinduoduo, JD, 618/Double 11 |
| 🇨🇳 China Market Localization Strategist | [marketing/marketing-china-market-localization-strategist.md](marketing/marketing-china-market-localization-strategist.md) | China market, localization, go-to-market, Douyin, Xiaohongshu |
| ✍️ Content Creator | [marketing/marketing-content-creator.md](marketing/marketing-content-creator.md) | editorial calendar, content strategy, brand storytelling, copy |
| 🌏 Cross-Border E-Commerce Specialist | [marketing/marketing-cross-border-ecommerce.md](marketing/marketing-cross-border-ecommerce.md) | Amazon, Shopee, AliExpress, Temu, TikTok Shop, logistics |
| 🎵 Douyin Strategist | [marketing/marketing-douyin-strategist.md](marketing/marketing-douyin-strategist.md) | Douyin, short-video, livestream commerce, algorithm |
| 🚀 Growth Hacker | [marketing/marketing-growth-hacker.md](marketing/marketing-growth-hacker.md) | user acquisition, viral loops, conversion funnels, growth channels |
| 📸 Instagram Curator | [marketing/marketing-instagram-curator.md](marketing/marketing-instagram-curator.md) | Instagram, visual storytelling, community building, aesthetic |
| 🎥 Kuaishou Strategist | [marketing/marketing-kuaishou-strategist.md](marketing/marketing-kuaishou-strategist.md) | Kuaishou, 快手, live commerce, grassroots audience |
| 💼 LinkedIn Content Creator | [marketing/marketing-linkedin-content-creator.md](marketing/marketing-linkedin-content-creator.md) | LinkedIn, thought leadership, personal brand, professional content |
| 🎙️ Livestream Commerce Coach | [marketing/marketing-livestream-commerce-coach.md](marketing/marketing-livestream-commerce-coach.md) | livestream, host training, Taobao Live, conversion closing |
| 🎧 Podcast Strategist | [marketing/marketing-podcast-strategist.md](marketing/marketing-podcast-strategist.md) | podcast, Xiaoyuzhou, Ximalaya, audio platforms, show positioning |
| 🔒 Private Domain Operator | [marketing/marketing-private-domain-operator.md](marketing/marketing-private-domain-operator.md) | WeCom, private domain, SCRM, Mini Program commerce |
| 💬 Reddit Community Builder | [marketing/marketing-reddit-community-builder.md](marketing/marketing-reddit-community-builder.md) | Reddit, community engagement, authentic content |
| 🔍 SEO Specialist | [marketing/marketing-seo-specialist.md](marketing/marketing-seo-specialist.md) | technical SEO, link building, organic search, content optimization |
| 🎬 Short-Video Editing Coach | [marketing/marketing-short-video-editing-coach.md](marketing/marketing-short-video-editing-coach.md) | CapCut, Premiere Pro, DaVinci Resolve, video editing, post-production |
| 📣 Social Media Strategist | [marketing/marketing-social-media-strategist.md](marketing/marketing-social-media-strategist.md) | social media, cross-platform campaigns, community, engagement |
| 🎵 TikTok Strategist | [marketing/marketing-tiktok-strategist.md](marketing/marketing-tiktok-strategist.md) | TikTok, viral content, algorithm optimization, community |
| 🐦 Twitter Engager | [marketing/marketing-twitter-engager.md](marketing/marketing-twitter-engager.md) | Twitter, thought leadership, viral threads, real-time engagement |
| 🎬 Video Optimization Specialist | [marketing/marketing-video-optimization-specialist.md](marketing/marketing-video-optimization-specialist.md) | YouTube, audience retention, thumbnails, video syndication |
| 📱 WeChat Official Account Manager | [marketing/marketing-wechat-official-account.md](marketing/marketing-wechat-official-account.md) | WeChat OA, subscriber engagement, content marketing |
| 🔥 Weibo Strategist | [marketing/marketing-weibo-strategist.md](marketing/marketing-weibo-strategist.md) | Weibo, trending topics, fan economy, public sentiment |
| 🌸 Xiaohongshu Specialist | [marketing/marketing-xiaohongshu-specialist.md](marketing/marketing-xiaohongshu-specialist.md) | Xiaohongshu, 小红书, lifestyle content, aesthetic storytelling |
| 🧠 Zhihu Strategist | [marketing/marketing-zhihu-strategist.md](marketing/marketing-zhihu-strategist.md) | Zhihu, 知乎, knowledge sharing, Q&A authority |

### Paid Media

| Agent | File | Triggers |
|-------|------|----------|
| 📋 Paid Media Auditor | [paid-media/paid-media-auditor.md](paid-media/paid-media-auditor.md) | Google Ads audit, Meta audit, account structure, ad spend waste |
| ✍️ Ad Creative Strategist | [paid-media/paid-media-creative-strategist.md](paid-media/paid-media-creative-strategist.md) | ad copywriting, RSA optimization, creative testing, asset groups |
| 📱 Paid Social Strategist | [paid-media/paid-media-paid-social-strategist.md](paid-media/paid-media-paid-social-strategist.md) | Meta ads, LinkedIn ads, TikTok ads, paid social, retargeting |
| 💰 PPC Campaign Strategist | [paid-media/paid-media-ppc-strategist.md](paid-media/paid-media-ppc-strategist.md) | PPC, search campaigns, shopping, bidding strategies, Google Ads |
| 📺 Programmatic & Display Buyer | [paid-media/paid-media-programmatic-buyer.md](paid-media/paid-media-programmatic-buyer.md) | display advertising, programmatic, DV360, ABM, media buying |
| 🔍 Search Query Analyst | [paid-media/paid-media-search-query-analyst.md](paid-media/paid-media-search-query-analyst.md) | search terms, negative keywords, intent mapping, query optimization |
| 📡 Tracking & Measurement Specialist | [paid-media/paid-media-tracking-specialist.md](paid-media/paid-media-tracking-specialist.md) | conversion tracking, GTM, GA4, attribution, Meta CAPI |

### Product

| Agent | File | Triggers |
|-------|------|----------|
| 🧠 Behavioral Nudge Engine | [product/product-behavioral-nudge-engine.md](product/product-behavioral-nudge-engine.md) | behavioral psychology, user motivation, nudge, interaction cadence |
| 🔍 Feedback Synthesizer | [product/product-feedback-synthesizer.md](product/product-feedback-synthesizer.md) | user feedback, synthesis, product insights, qualitative analysis |
| 🧭 Product Manager | [product/product-manager.md](product/product-manager.md) | product lifecycle, roadmap, stakeholder alignment, go-to-market |
| 🎯 Sprint Prioritizer | [product/product-sprint-prioritizer.md](product/product-sprint-prioritizer.md) | sprint planning, feature prioritization, backlog, resource allocation |
| 🔭 Trend Researcher | [product/product-trend-researcher.md](product/product-trend-researcher.md) | market intelligence, emerging trends, competitive analysis, opportunity |

### Project Management

| Agent | File | Triggers |
|-------|------|----------|
| 🧪 Experiment Tracker | [project-management/project-management-experiment-tracker.md](project-management/project-management-experiment-tracker.md) | A/B tests, experiments, hypothesis validation, data-driven |
| 📋 Jira Workflow Steward | [project-management/project-management-jira-workflow-steward.md](project-management/project-management-jira-workflow-steward.md) | Jira, Git workflow, traceable commits, structured PRs |
| 🐑 Project Shepherd | [project-management/project-management-project-shepherd.md](project-management/project-management-project-shepherd.md) | cross-functional, timeline management, stakeholder, coordination |
| 🏭 Studio Operations | [project-management/project-management-studio-operations.md](project-management/project-management-studio-operations.md) | studio efficiency, process optimization, resource coordination |
| 🎬 Studio Producer | [project-management/project-management-studio-producer.md](project-management/project-management-studio-producer.md) | project orchestration, resource allocation, portfolio management |
| 📝 Senior Project Manager | [project-management/project-manager-senior.md](project-management/project-manager-senior.md) | specs to tasks, scope management, project planning, realistic delivery |

### Sales

| Agent | File | Triggers |
|-------|------|----------|
| 🗺️ Account Strategist | [sales/sales-account-strategist.md](sales/sales-account-strategist.md) | land-and-expand, stakeholder mapping, QBR, net revenue retention |
| 🏋️ Sales Coach | [sales/sales-coach.md](sales/sales-coach.md) | rep development, call coaching, deal strategy, forecast accuracy |
| ♟️ Deal Strategist | [sales/sales-deal-strategist.md](sales/sales-deal-strategist.md) | MEDDPICC, competitive positioning, win planning, B2B sales |
| 🔍 Discovery Coach | [sales/sales-discovery-coach.md](sales/sales-discovery-coach.md) | discovery methodology, question design, gap quantification, buying motivation |
| 🛠️ Sales Engineer | [sales/sales-engineer.md](sales/sales-engineer.md) | pre-sales, demo engineering, POC scoping, competitive battlecards |
| 🎯 Outbound Strategist | [sales/sales-outbound-strategist.md](sales/sales-outbound-strategist.md) | outbound prospecting, ICP, multi-channel sequences, personalization |
| 📊 Pipeline Analyst | [sales/sales-pipeline-analyst.md](sales/sales-pipeline-analyst.md) | pipeline health, deal velocity, forecast accuracy, CRM data |
| 🏹 Proposal Strategist | [sales/sales-proposal-strategist.md](sales/sales-proposal-strategist.md) | RFP, proposals, win themes, executive summary, competitive positioning |

### Spatial Computing

| Agent | File | Triggers |
|-------|------|----------|
| 🍎 macOS Spatial/Metal Engineer | [spatial-computing/macos-spatial-metal-engineer.md](spatial-computing/macos-spatial-metal-engineer.md) | Swift, Metal, 3D rendering, Vision Pro, macOS |
| 🖥️ Terminal Integration Specialist | [spatial-computing/terminal-integration-specialist.md](spatial-computing/terminal-integration-specialist.md) | terminal emulation, SwiftTerm, text rendering |
| 🥽 visionOS Spatial Engineer | [spatial-computing/visionos-spatial-engineer.md](spatial-computing/visionos-spatial-engineer.md) | visionOS, SwiftUI, volumetric interfaces, Liquid Glass |
| 🕹️ XR Cockpit Interaction Specialist | [spatial-computing/xr-cockpit-interaction-specialist.md](spatial-computing/xr-cockpit-interaction-specialist.md) | XR cockpit, immersive controls, control systems |
| 🌐 XR Immersive Developer | [spatial-computing/xr-immersive-developer.md](spatial-computing/xr-immersive-developer.md) | WebXR, AR/VR, browser-based, immersive applications |
| 🫧 XR Interface Architect | [spatial-computing/xr-interface-architect.md](spatial-computing/xr-interface-architect.md) | spatial interaction, XR interface design, AR/VR environments |

### Specialized

| Agent | File | Triggers |
|-------|------|----------|
| 💸 Accounts Payable Agent | [specialized/accounts-payable-agent.md](specialized/accounts-payable-agent.md) | payments, invoices, crypto, fiat, stablecoins |
| 🔐 Agentic Identity & Trust Architect | [specialized/agentic-identity-trust.md](specialized/agentic-identity-trust.md) | agent identity, authentication, trust verification, multi-agent |
| 🎛️ Agents Orchestrator | [specialized/agents-orchestrator.md](specialized/agents-orchestrator.md) | pipeline manager, workflow orchestration, dev lifecycle |
| ⚙️ Automation Governance Architect | [specialized/automation-governance-architect.md](specialized/automation-governance-architect.md) | governance, n8n, automation audit, risk, maintainability |
| 🛡️ Blockchain Security Auditor | [specialized/blockchain-security-auditor.md](specialized/blockchain-security-auditor.md) | smart contract audit, vulnerability, exploit, DeFi |
| 📋 Compliance Auditor | [specialized/compliance-auditor.md](specialized/compliance-auditor.md) | SOC 2, ISO 27001, HIPAA, PCI-DSS, certification |
| 📚 Corporate Training Designer | [specialized/corporate-training-designer.md](specialized/corporate-training-designer.md) | training design, curriculum, instructional design, leadership programs |
| 🗄️ Data Consolidation Agent | [specialized/data-consolidation-agent.md](specialized/data-consolidation-agent.md) | sales data, dashboards, territory, pipeline summaries |
| 🏛️ Government Digital Presales Consultant | [specialized/government-digital-presales-consultant.md](specialized/government-digital-presales-consultant.md) | China government, digital transformation, bid documents, ToG |
| ⚕️ Healthcare Marketing Compliance Specialist | [specialized/healthcare-marketing-compliance.md](specialized/healthcare-marketing-compliance.md) | healthcare compliance, Advertising Law, pharma, medical devices |
| 🕸️ Identity Graph Operator | [specialized/identity-graph-operator.md](specialized/identity-graph-operator.md) | identity graph, entity resolution, multi-agent, canonical |
| 🔎 LSP/Index Engineer | [specialized/lsp-index-engineer.md](specialized/lsp-index-engineer.md) | LSP, code intelligence, semantic indexing, language server |
| 🎯 Recruitment Specialist | [specialized/recruitment-specialist.md](specialized/recruitment-specialist.md) | recruitment, talent acquisition, hiring platforms, labor law |
| 📤 Report Distribution Agent | [specialized/report-distribution-agent.md](specialized/report-distribution-agent.md) | report distribution, sales reports, territorial, automation |
| 📊 Sales Data Extraction Agent | [specialized/sales-data-extraction-agent.md](specialized/sales-data-extraction-agent.md) | Excel monitoring, sales metrics, MTD, YTD, live reporting |
| 🏗️ Civil Engineer | [specialized/specialized-civil-engineer.md](specialized/specialized-civil-engineer.md) | structural analysis, geotechnical, building codes, Eurocode |
| 🌍 Cultural Intelligence Strategist | [specialized/specialized-cultural-intelligence-strategist.md](specialized/specialized-cultural-intelligence-strategist.md) | cultural intelligence, inclusion, global context, intersectional |
| 🗣️ Developer Advocate | [specialized/specialized-developer-advocate.md](specialized/specialized-developer-advocate.md) | developer community, DX, platform adoption, technical content |
| 📄 Document Generator | [specialized/specialized-document-generator.md](specialized/specialized-document-generator.md) | PDF, PPTX, DOCX, XLSX, document creation, charts |
| 🇫🇷 French Consulting Market Navigator | [specialized/specialized-french-consulting-market.md](specialized/specialized-french-consulting-market.md) | French ESN, freelance, portage salarial, rate positioning |
| 🇰🇷 Korean Business Navigator | [specialized/specialized-korean-business-navigator.md](specialized/specialized-korean-business-navigator.md) | Korean business, 품의, nunchi, KakaoTalk etiquette |
| 🔌 MCP Builder | [specialized/specialized-mcp-builder.md](specialized/specialized-mcp-builder.md) | MCP server, custom tools, AI agent extensions, Model Context Protocol |
| 🔬 Model QA Specialist | [specialized/specialized-model-qa.md](specialized/specialized-model-qa.md) | ML audit, calibration testing, interpretability, model validation |
| ☁️ Salesforce Architect | [specialized/specialized-salesforce-architect.md](specialized/specialized-salesforce-architect.md) | Salesforce, multi-cloud, governor limits, data model governance |
| 🗺️ Workflow Architect | [specialized/specialized-workflow-architect.md](specialized/specialized-workflow-architect.md) | workflow trees, branch conditions, failure modes, handoff contracts |
| 🎓 Study Abroad Advisor | [specialized/study-abroad-advisor.md](specialized/study-abroad-advisor.md) | study abroad, application strategy, visa, school selection |
| 🔗 Supply Chain Strategist | [specialized/supply-chain-strategist.md](specialized/supply-chain-strategist.md) | supply chain, procurement, sourcing, quality control |
| 🗃️ ZK Steward | [specialized/zk-steward.md](specialized/zk-steward.md) | Zettelkasten, knowledge base, atomic notes, cross-domain |

### Support

| Agent | File | Triggers |
|-------|------|----------|
| 📊 Analytics Reporter | [support/support-analytics-reporter.md](support/support-analytics-reporter.md) | dashboards, statistical analysis, KPIs, data visualization |
| 📝 Executive Summary Generator | [support/support-executive-summary-generator.md](support/support-executive-summary-generator.md) | executive summary, McKinsey SCQA, C-suite, strategy consulting |
| 💰 Finance Tracker | [support/support-finance-tracker.md](support/support-finance-tracker.md) | financial planning, budget, cash flow, forecasting |
| 🏢 Infrastructure Maintainer | [support/support-infrastructure-maintainer.md](support/support-infrastructure-maintainer.md) | system reliability, performance, technical operations |
| ⚖️ Legal Compliance Checker | [support/support-legal-compliance-checker.md](support/support-legal-compliance-checker.md) | legal, compliance, regulations, data handling, jurisdictions |
| 💬 Support Responder | [support/support-support-responder.md](support/support-support-responder.md) | customer support, issue resolution, user experience |

### Testing

| Agent | File | Triggers |
|-------|------|----------|
| ♿ Accessibility Auditor | [testing/testing-accessibility-auditor.md](testing/testing-accessibility-auditor.md) | WCAG, assistive technologies, screen reader, inclusive design |
| 🔌 API Tester | [testing/testing-api-tester.md](testing/testing-api-tester.md) | API validation, performance testing, quality assurance |
| 📸 Evidence Collector | [testing/testing-evidence-collector.md](testing/testing-evidence-collector.md) | QA, screenshots, visual proof, bug verification |
| ⏱️ Performance Benchmarker | [testing/testing-performance-benchmarker.md](testing/testing-performance-benchmarker.md) | performance testing, load testing, system optimization |
| 🧐 Reality Checker | [testing/testing-reality-checker.md](testing/testing-reality-checker.md) | production readiness, evidence-based, certification, quality gate |
| 📋 Test Results Analyzer | [testing/testing-test-results-analyzer.md](testing/testing-test-results-analyzer.md) | test results, quality metrics, analysis, actionable insights |
| 🔧 Tool Evaluator | [testing/testing-tool-evaluator.md](testing/testing-tool-evaluator.md) | tool assessment, software evaluation, productivity optimization |
| ⚡ Workflow Optimizer | [testing/testing-workflow-optimizer.md](testing/testing-workflow-optimizer.md) | process improvement, workflow automation, bottleneck analysis |

### Strategy (Reference Materials)

The `strategy/` directory contains orchestration docs, playbooks, and runbooks — not individual agents.

| Document | File | Purpose |
|----------|------|---------|
| Nexus Strategy | [strategy/nexus-strategy.md](strategy/nexus-strategy.md) | Multi-agent coordination strategy |
| Agent Activation Prompts | [strategy/coordination/agent-activation-prompts.md](strategy/coordination/agent-activation-prompts.md) | Prompt templates for activating agents |
| Handoff Templates | [strategy/coordination/handoff-templates.md](strategy/coordination/handoff-templates.md) | Inter-agent handoff contracts |
| Phase 0: Discovery | [strategy/playbooks/phase-0-discovery.md](strategy/playbooks/phase-0-discovery.md) | Discovery phase playbook |
| Phase 1: Strategy | [strategy/playbooks/phase-1-strategy.md](strategy/playbooks/phase-1-strategy.md) | Strategy phase playbook |
| Phase 2: Foundation | [strategy/playbooks/phase-2-foundation.md](strategy/playbooks/phase-2-foundation.md) | Foundation phase playbook |
| Phase 3: Build | [strategy/playbooks/phase-3-build.md](strategy/playbooks/phase-3-build.md) | Build phase playbook |
| Phase 4: Hardening | [strategy/playbooks/phase-4-hardening.md](strategy/playbooks/phase-4-hardening.md) | Hardening phase playbook |
| Phase 5: Launch | [strategy/playbooks/phase-5-launch.md](strategy/playbooks/phase-5-launch.md) | Launch phase playbook |
| Phase 6: Operate | [strategy/playbooks/phase-6-operate.md](strategy/playbooks/phase-6-operate.md) | Operations phase playbook |
| Scenario: Enterprise Feature | [strategy/runbooks/scenario-enterprise-feature.md](strategy/runbooks/scenario-enterprise-feature.md) | Enterprise feature runbook |
| Scenario: Incident Response | [strategy/runbooks/scenario-incident-response.md](strategy/runbooks/scenario-incident-response.md) | Incident response runbook |
| Scenario: Marketing Campaign | [strategy/runbooks/scenario-marketing-campaign.md](strategy/runbooks/scenario-marketing-campaign.md) | Marketing campaign runbook |
| Scenario: Startup MVP | [strategy/runbooks/scenario-startup-mvp.md](strategy/runbooks/scenario-startup-mvp.md) | Startup MVP runbook |
| Executive Brief | [strategy/EXECUTIVE-BRIEF.md](strategy/EXECUTIVE-BRIEF.md) | Executive summary and strategic overview of NEXUS |
| Quickstart Guide | [strategy/QUICKSTART.md](strategy/QUICKSTART.md) | Quick-start guide for NEXUS deployment |

### Examples (Reference Materials)

The `examples/` directory contains workflow examples — not individual agents.

| Document | File | Purpose |
|----------|------|---------|
| Nexus Spatial Discovery | [examples/nexus-spatial-discovery.md](examples/nexus-spatial-discovery.md) | Spatial computing discovery workflow |
| Workflow: Book Chapter | [examples/workflow-book-chapter.md](examples/workflow-book-chapter.md) | Book chapter creation workflow |
| Workflow: Landing Page | [examples/workflow-landing-page.md](examples/workflow-landing-page.md) | Landing page build workflow |
| Workflow: Startup MVP | [examples/workflow-startup-mvp.md](examples/workflow-startup-mvp.md) | Startup MVP workflow |
| Workflow: With Memory | [examples/workflow-with-memory.md](examples/workflow-with-memory.md) | Memory-enabled workflow |

---

## Cross-Reference: Agents ↔ Existing Skills

| Agent | Complementary Skills (from `~/.claude/skills/`) |
|-------|-----------------------------------------------|
| 🗄️ Database Optimizer | `explain-analyze-validation`, `index-creation-concurrently`, `autovacuum-bloat-management`, `pg-stat-statements-observability`, `fillfactor-storage-tuning` |
| 🏗️ Backend Architect | `connection-pooling-timeout-safety`, `security-best-practices`, `cloudflare-deploy`, `aspnet-core` |
| 🔧 Data Engineer | `spreadsheet`, `dry-run-gate-pattern` |
| 👁️ Code Reviewer | `deep-grep-code-review`, `document-code-review`, `cross-reference-integrity` |
| 🔒 Security Engineer | `security-best-practices`, `security-threat-model`, `security-ownership-map` |
| 🖥️ Frontend Developer | `figma`, `figma-implement-design`, `cloudflare-deploy`, `develop-web-game` |
| ⚙️ DevOps Automator | `cloudflare-deploy`, `vercel-deploy`, `netlify-deploy`, `render-deploy` |
| 📚 Technical Writer | `technical-document-craftsmanship`, `long-document-revision-protocol`, `doc`, `pdf`, `voice-and-cadence-consistency` |
| 📝 Senior Project Manager | `linear`, `notion-spec-to-implementation`, `notion-meeting-intelligence`, `notion-research-documentation` |
| 🏹 Proposal Strategist | `professional-identity`, `slides`, `pdf`, `spreadsheet` |
| 📲 Mobile App Builder | `develop-web-game`, `playwright` |
| 🔬 UX Researcher | `figma`, `playwright`, `figma-implement-design` |
| ✍️ Content Creator | `llm-system-prompt-engineering`, `imagegen`, `sora`, `speech` |
| 🎨 UI Designer | `figma`, `figma-implement-design` |
| 📐 UX Architect | `figma`, `figma-implement-design` |
| 🎬 Visual Storyteller | `imagegen`, `sora`, `slides` |
| 🚀 Growth Hacker | `cloudflare-deploy`, `llm-system-prompt-engineering` |
| 🔍 SEO Specialist | `cloudflare-deploy` |
| 📣 Social Media Strategist | `llm-system-prompt-engineering` |
| 🏛️ Software Architect | `aspnet-core`, `security-best-practices`, `security-threat-model` |
| 🛡️ SRE | `cloudflare-deploy`, `pg-stat-statements-observability`, `arm-synthetics` |
| 🚨 Incident Response Commander | `cloudflare-deploy`, `incident-capture` |
| 🌿 Git Workflow Master | `yeet`, `gh-address-comments`, `gh-fix-ci` |
| 📄 Document Generator | `doc`, `pdf`, `slides`, `spreadsheet` |
| 🤖 AI Engineer | `llm-system-prompt-engineering`, `openai-docs`, `jupyter-notebook` |
| 📸 Evidence Collector | `screenshot`, `playwright` |
| 🧐 Reality Checker | `screenshot`, `playwright` |
| ♿ Accessibility Auditor | `playwright`, `figma` |
| 🔌 API Tester | `playwright` |
| ⏱️ Performance Benchmarker | `explain-analyze-validation`, `pg-stat-statements-observability` |
| ⚡ Workflow Optimizer | `notion-spec-to-implementation`, `linear` |
| 📊 Analytics Reporter | `spreadsheet`, `jupyter-notebook` |
| 📝 Executive Summary Generator | `slides`, `pdf`, `doc` |
| 💰 Finance Tracker | `spreadsheet` |
| 🏢 Infrastructure Maintainer | `cloudflare-deploy`, `vercel-deploy`, `netlify-deploy`, `render-deploy` |
| ⚖️ Legal Compliance Checker | `security-best-practices` |
| 🔌 MCP Builder | `chatgpt-apps`, `skill-creator` |
| 🗃️ ZK Steward | `notion-knowledge-capture`, `notion-research-documentation` |
| 📷 Image Prompt Engineer | `imagegen`, `image-analyzer` |
| 🧬 AI Data Remediation Engineer | `dry-run-gate-pattern`, `idempotent-sql-design` |
| 🎯 Threat Detection Engineer | `security-threat-model`, `security-ownership-map` |
| ⛓️ Solidity Smart Contract Engineer | `security-best-practices` |
| 🛡️ Blockchain Security Auditor | `security-best-practices`, `security-threat-model` |
| 📋 Jira Workflow Steward | `yeet`, `gh-address-comments`, `gh-fix-ci`, `linear` |
| 🎬 Studio Producer | `notion-spec-to-implementation`, `notion-meeting-intelligence`, `slides` |
| 💼 LinkedIn Content Creator | `professional-identity` |
| 📘 Book Co-Author | `doc`, `pdf`, `long-document-revision-protocol` |
| 🎬 Short-Video Editing Coach | `sora` |
| 📋 Paid Media Auditor | `spreadsheet` |
| 📡 Tracking & Measurement Specialist | `playwright` |
| 🧠 Behavioral Nudge Engine | `figma`, `playwright` |
| 🔬 Model QA Specialist | `jupyter-notebook`, `spreadsheet` |

---

## Statistics

- **Total agents**: 152
- **Divisions with agents**: 13
- **Reference directories**: 2 (strategy, examples)

| Division | Count |
|----------|-------|
| Academic | 5 |
| Design | 8 |
| Engineering | 28 |
| Game Development | 5 |
| Marketing | 30 |
| Paid Media | 7 |
| Product | 5 |
| Project Management | 6 |
| Sales | 8 |
| Spatial Computing | 6 |
| Specialized | 29 |
| Support | 7 |
| Testing | 8 |
| **Total** | **152** |
