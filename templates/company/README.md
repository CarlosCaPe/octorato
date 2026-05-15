# How to Create Your Company Brain

Your company brain is the private layer of the Octopus Brain Framework. It contains your identity, client definitions, and company-specific skills. It is **never committed** to the framework repo.

## Setup

```bash
# 1. Copy templates to create your company brain
cp -r ~/.claude/templates/company/ ~/.claude/company/

# 2. Rename template files
cd ~/.claude/company
mv COMPANY.md.template COMPANY.md
mv config/arms.json.template config/arms.json

# 3. Edit COMPANY.md — fill in your identity, arms, connections
nano COMPANY.md

# 4. Edit config/arms.json — define your client projects and their tech stacks
nano config/arms.json

# 5. (Optional) Create company-specific skills
mkdir -p skills/professional-identity
# Use ~/.claude/templates/skill/SKILL.md.template as a starting point

# 6. (Optional) Create company assets directory
mkdir -p assets/
```

## Directory Structure

```
~/.claude/company/
├── COMPANY.md          <- Your identity, arms, connections (edit this)
├── config/
│   └── arms.json       <- Arm definitions for the connectome engine
├── skills/             <- Company-specific skills (private workflows)
├── assets/             <- Signatures, logos, etc.
├── scripts/            <- Company-specific scripts
└── neural_activity.json <- Hebbian learning log (auto-generated)
```

## What Goes Here vs. Framework

| Company Brain (private) | Framework (public) |
|------------------------|-------------------|
| Your name, rates, CV | Generic agent personas |
| Client names and codes | Reusable skills and techniques |
| Database connection names | The 4D Paradigm rules |
| Company-specific workflows | Connectome engine |
| Voice/communication style | Enforcement scripts |
| Assets (signatures, logos) | Templates |

## The Inheritance Chain

When the AI agent works in a project:

```
1. Load ~/.claude/CLAUDE.md           <- Framework rules (CLASS)
2. Load ~/.claude/company/COMPANY.md  <- Company identity (OBJECT)
3. Load <project>/.claude/CLAUDE.md   <- Project context (ARM)

Resolution: project overrides company overrides framework
```
