// Generation prompts ported verbatim from src/app/[owner]/[repo]/page.tsx and the
// slides/workshop pages. All generated content is hardcoded Chinese (China-region
// audience) — no i18n switching.

// Workshop markdown prompt (ported from workshop/page.tsx).
export function buildWorkshopPrompt(opts: {
  owner: string
  repo: string
  wikiContent: string
}): string {
  const { owner, repo, wikiContent } = opts
  return `Create a comprehensive workshop for learning how to use and contribute to the ${owner}/${repo} repository.

I'll provide you with information from the project's wiki to help you create a more accurate and relevant workshop.

${wikiContent}

This workshop should be designed as a hands-on tutorial that guides users through understanding, using, and potentially contributing to this project. The workshop should be highly readable and optimized for quick onboarding of new users.

The workshop should include:
1. A series of progressive exercises that build on each other (at least 3-4 exercises)
2. Clear instructions for each exercise with step-by-step guidance
3. Code examples and snippets where appropriate
4. "Challenge" sections that encourage deeper exploration
5. Solutions for each exercise and challenge (in collapsible sections using <details> tags)
6. Explanations that connect the exercises to the actual codebase

Format the workshop in Markdown with the following structure:

# ${repo} Workshop

## Introduction
- Brief overview of the project
- What users will learn in this workshop
- Prerequisites and setup instructions

## Exercise 1: [First Core Concept]
- Explanation of the concept
- Step-by-step instructions with clear formatting
- Expected outcome
- Challenge (optional harder task)
- Solution (in a collapsible section using <details> tags)

## Exercise 2: [Second Core Concept]
## Exercise 3: [Third Core Concept]

## Final Project
- A culminating exercise that brings together multiple concepts
- Clear success criteria
- Solution

## Next Steps
- Suggestions for further learning
- How to contribute to the project
- Additional resources

IMPORTANT FORMATTING GUIDELINES:
1. Use clear headings and subheadings with proper hierarchy
2. Use bullet points and numbered lists for clarity
3. Highlight important information in **bold** or with blockquotes
4. Use code blocks with proper syntax highlighting
5. Include Mermaid diagrams where they would help illustrate concepts or workflows
6. Put solutions in collapsible <details> sections
7. Use tables for comparing options or summarizing information

IMPORTANT CONTENT GUIDELINES:
1. Make sure each exercise focuses on a REAL aspect of the ${repo} repository
2. Use REAL code examples from the repository, not generic examples
3. Create exercises that are practical and relevant to the actual codebase
4. The final project should be challenging but achievable
5. Ensure the workshop is specific to this repository, not generic

Make the workshop content in Chinese (中文).`
}

// Slide-plan prompt: returns a numbered list of slide titles (ported from slides/page.tsx).
export function buildSlidePlanPrompt(opts: {
  owner: string
  repo: string
  wikiContent: string
}): string {
  const { owner, repo, wikiContent } = opts
  return `Create an engaging outline for a high-quality marketing slide presentation about the ${owner}/${repo} repository.

Based on this wiki content:
${wikiContent}

I need a numbered list of 7-8 creative slide titles with brief descriptions for a professional marketing presentation. Think of this as a pitch deck that would impress potential users or investors.

Focus on:
- Compelling value propositions
- Unique selling points
- Impressive features and capabilities
- Real-world applications and benefits
- Visually interesting concepts that can be represented creatively

For example, instead of generic titles like "Introduction" or "Features", use more engaging titles like:
1. "Revolutionizing Development with ${repo}"
2. "Unlock Powerful Capabilities with Our Innovative Architecture"
3. "How ${repo} Transforms Your Workflow"

Give me the numbered list with brief descriptions for each slide. Be creative but professional.`
}

// Single-slide HTML prompt (ported, with the lengthy CSS example trimmed).
export function buildSlidePrompt(opts: {
  owner: string
  repo: string
  slideTitle: string
  slideDescription: string
  slideNumber: number
  totalSlides: number
  wikiContent: string
}): string {
  const { owner, repo, slideTitle, slideDescription, slideNumber, totalSlides, wikiContent } = opts
  return `Create a single HTML slide about the ${owner}/${repo} repository with the title "${slideTitle}".

This is slide ${slideNumber} of ${totalSlides} in the presentation.
${slideDescription ? `The slide should cover: ${slideDescription}` : ''}

Use the following wiki content as reference:
${wikiContent}

I need ONLY the HTML for this slide. The slide should maintain a consistent dark theme with gradients and professional styling, but BE CREATIVE with the content and layout.

IMPORTANT LAYOUT REQUIREMENTS:
1. The slide MUST be designed for a 16:9 HORIZONTAL layout (landscape orientation)
2. All content MUST fit within the visible area without requiring scrolling
3. Text must be properly sized and positioned for readability in a presentation context
4. Use grid or flexbox layouts to ensure proper horizontal organization of content

MARKETING QUALITY:
Create a genuinely high-quality marketing slide that would impress potential users or investors. Use compelling language and professional marketing techniques.

You can use:
- Two or three-column layouts for better horizontal space utilization
- Engaging marketing copy with concise bullet points (no more than 4-5 per slide)
- Icons from Font Awesome (already included)
- Creative use of gradients, shadows, and visual elements

The root element MUST be <div class="slide"> with width:100%/height:100% and a dark gradient background (linear-gradient(135deg, #0d1117 0%, #161b22 100%)). Include a <style> block for the slide's CSS.

Please return ONLY the HTML with no markdown formatting or code blocks. Just the raw HTML for the slide.`
}

// Page archetypes — a single rigid template on every page is what made wikis read
// the same ("功能架构 / 核心API / 数据模型 / 总结" everywhere). Each page carries a TYPE
// (assigned during planning) that picks a DIFFERENT body. Keep in sync with
// api/wiki_generator.py (_PAGE_BODY / PAGE_TYPES).
export type PagePromptType = 'overview' | 'architecture' | 'feature' | 'reference' | 'cross-cutting' | 'guide' | 'glossary'

const PAGE_TYPES: PagePromptType[] = ['overview', 'architecture', 'feature', 'reference', 'cross-cutting', 'guide', 'glossary']

export function normalizePageType(value?: string): PagePromptType {
  const t = (value || '').trim().toLowerCase().replace(/[_\s]/g, '-')
  if (['crosscutting', 'cross', 'shared', 'cross-cutting-concern'].includes(t)) return 'cross-cutting'
  if (['terms', 'term', 'terminology', 'glossaries', '术语', '术语表'].includes(t)) return 'glossary'
  return (PAGE_TYPES as string[]).includes(t) ? (t as PagePromptType) : 'feature'
}

// All headings are FIXED Chinese — the model must copy them verbatim.
const PAGE_BODY: Record<PagePromptType, string> = {
  feature: `This is a FEATURE / SCREEN / business-module page. Structure the WHOLE page as a traceable chain and use THESE THREE H2 sections in EXACTLY this order, with EXACTLY these Chinese headings copied VERBATIM (never English names like "Business Flow"). Do NOT merge, reorder, or replace them with a generic outline:

## 业务流程
- Describe what the feature does as a NUMBERED business/user flow — 步骤1、步骤2、… — including decision branches, the roles/actors involved, preconditions, and key business rules.
- MANDATORY: include at least one Mermaid flowchart (\`graph TD\`) that visualizes this flow with its steps and branches. If the flow crosses front-end / back-end / third-party systems, ALSO add a \`sequenceDiagram\`. A 业务流程 section with NO diagram is unacceptable.

## 代码职责
- Map EACH numbered business step above to the code that implements it, as a Markdown table with columns: 业务步骤 | 文件/组件/函数 | 职责与关键逻辑 | Sources.
- Show how the parts collaborate (e.g. page/component → API wrapper → backend endpoint); add a Mermaid \`sequenceDiagram\` or a call-chain \`graph TD\` when it clarifies the call path.
- Call out WHERE to change / extend behaviour (the key extension points).

## 测试流程
- Describe how to verify the feature as test scenarios that trace back to the business steps/rules above, as a Markdown table with columns: 场景 | 前置条件 | 步骤 | 预期结果.
- Cover the happy path AND edge / exception cases (empty data, no permission, role differences, concurrency, failure handling).
- Add a test flowchart (\`graph TD\`) when the flow has non-trivial conditional branches.

Keep the three sections traceable: the SAME numbered steps should be referenceable across 业务流程 → 代码职责 → 测试流程, so a reader can follow one step end to end.`,

  reference: `This is a REFERENCE page (API / data model / configuration). Prefer STRUCTURED TABLES over prose — keep narrative to a minimum:
- API: one row per endpoint/method with request params, response fields, and error codes.
- Data model: entities, fields, types, constraints and relationships (add an \`erDiagram\` when it clarifies relationships).
- Configuration: one row per option with its default, effect and scope.
Document only what is specific here; do NOT re-explain cross-cutting mechanisms.`,

  overview: `This is an OVERVIEW / entry page for ALL audiences (product, engineering, QA):
- What the project/module does, its core value, and who its users are (2-3 short paragraphs).
- A feature map: use a Mermaid \`graph TD\` to show the main modules and how they relate.
- A 「后续阅读」 section (use this EXACT Chinese heading): link the most important module/reference pages using REAL page titles, in the exact form \`[页面标题](#页面标题)\` — never invent page names or English slugs.
Keep it high-level and leave the details to the linked pages.`,

  architecture: `This is an ARCHITECTURE page:
- The layers and main components, shown with a Mermaid architecture diagram (\`graph TD\`).
- Key data flows / call chains, shown with a Mermaid \`sequenceDiagram\` or flowchart.
- Technology choices and notable design decisions, each grounded in the source files.`,

  'cross-cutting': `This is the SINGLE AUTHORITATIVE page for a cross-cutting concern (e.g. authentication & permissions, front-end/back-end communication, environment/configuration). Every other page LINKS here instead of repeating it, so be COMPLETE:
- Explain the whole mechanism in one place, end to end.
- Show the overall flow with a Mermaid diagram.
- Explain how other modules integrate with / reuse it (what a feature page should link to rather than restate).`,

  guide: `This is a HOW-TO / guide page (setup, deployment, common operational tasks). Make it ACTIONABLE:
- Prerequisites.
- Numbered, step-by-step instructions with concrete commands / config examples.
- Common problems and troubleshooting.`,

  glossary: `This is the project GLOSSARY — a BUSINESS FIELD dictionary (业务术语与字段词典). Be COMPREHENSIVE — readers expect FULL coverage, not a handful of terms; do NOT summarize or stop early.
- Enumerate EVERY business term, document/entity, fee item, status and enum used across the project, TOGETHER WITH its code identifier: the API/form field name (e.g. 运单号 → waybillNo) or the enum/constant code (e.g. 订单转运单 → ORDER).
- ONLY business vocabulary. Do NOT include generic page/UI wording — placeholders (请输入/请选择), buttons (确定/取消/保存/查询), date shortcuts (昨天/最近一周), navigation (首页/登录) — those are page attributes, not business terms.
- GROUP terms by domain (e.g. 运单、费用、网点、货物、服务与派送 …) with a Chinese H2 or H3 per group; within each group use a Markdown table with columns: 术语 | 字段名/编码 | 定义 | 所属模块.
- Fill the 字段名/编码 column from the source files; leave it as - only when no identifier exists. Link the 所属模块 cell to the relevant wiki page with \`[Link Text](#page-anchor-or-id)\` when possible.
- Include acronyms and bilingual mappings (e.g. SSO, VIP, GIS; 面单 / waybill). Aim for breadth — a real business system has dozens of terms.`,
}

const DEDUP_RULE = `
AVOID DUPLICATION: shared mechanisms — authentication & permissions, front-end/back-end communication, environment/configuration, shared API conventions — are documented ONCE on their own dedicated cross-cutting pages. If this page touches any of them, LINK to that page with \`[Link Text](#page-anchor-or-id)\` instead of re-explaining it; describe only what is SPECIFIC to this page.
`

// Shared page-type vocabulary injected into the structure prompt so each page gets an
// archetype; buildPagePrompt then picks a distinct structure per type.
const TYPE_VOCAB = `Classify EACH page with a <type> from: overview | architecture | feature | reference | cross-cutting | guide.
- feature: a screen / business feature (MOST module pages) — written as 业务流程 → 代码职责 → 测试流程, with a mandatory flowchart.
- reference: an API, data-model, or configuration reference (mostly tables).
- cross-cutting: a shared mechanism documented ONCE and linked from elsewhere (authentication & permissions, front-end/back-end communication, environment/config).
- overview / architecture / guide: foundational topics (project overview, system architecture, setup/deployment).
Create AT MOST ONE cross-cutting page per shared mechanism — do NOT repeat auth/communication/config on every module page.`

// Page-content prompt. `filePathsList` is the pre-built markdown list of source
// files (e.g. "- [path](url)\n- ..."). `pageType` selects the body structure.
export function buildPagePrompt(opts: {
  pageTitle: string
  filePathsList: string
  pageType?: string
}): string {
  const { pageTitle, filePathsList } = opts
  const ptype = normalizePageType(opts.pageType)
  const body = PAGE_BODY[ptype]
  const dedup = ptype === 'cross-cutting' ? '' : DEDUP_RULE
  return `You are an expert technical writer and software architect.
Your task is to generate a comprehensive and accurate technical wiki page in Markdown format about a specific feature, system, or module within a given software project.

You will be given:
1. The "[WIKI_PAGE_TOPIC]" for the page you need to create.
2. A list of "[RELEVANT_SOURCE_FILES]" from the project that you MUST use as the sole basis for the content. You have access to the full content of these files. You MUST use AT LEAST 5 relevant source files for comprehensive coverage - if fewer are provided, search for additional related files in the codebase.

CRITICAL STARTING INSTRUCTION:
The very first thing on the page MUST be a \`<details>\` block listing ALL the \`[RELEVANT_SOURCE_FILES]\` you used to generate the content. There MUST be AT LEAST 5 source files listed - if fewer were provided, you MUST find additional related files to include.
Format it exactly like this:
<details>
<summary>相关源文件</summary>

Remember, do not provide any acknowledgements, disclaimers, apologies, or any other preface before the \`<details>\` block. JUST START with the \`<details>\` block.
以下文件用于生成本页面时作为上下文参考：

${filePathsList}
<!-- Add additional relevant files if fewer than 5 were provided -->
</details>

Immediately after the \`<details>\` block, the main title of the page should be a H1 Markdown heading: \`# ${pageTitle}\`.

Then a concise 1-2 sentence introduction of "${pageTitle}" (its purpose and scope within the project), and after it the body below.

PAGE BODY — this page's type is "${ptype}". Follow the structure for THIS type. Do NOT fall back to a generic "architecture / core API / data model / summary" outline; use only the sections called for here, and ground every section ONLY in the \`[RELEVANT_SOURCE_FILES]\`:

${body}
${dedup}
FORMATTING RULES (apply to all of the above):

- **Mermaid Diagrams:** Use Mermaid diagrams where they clarify a flow, relationship, or schema (\`flowchart TD\`, \`sequenceDiagram\`, \`classDiagram\`, \`erDiagram\`, \`graph TD\`), derived directly from the source files, with a one-line explanation near each. All diagrams MUST follow strict vertical orientation:
   - Use "graph TD" (top-down) for flow diagrams; NEVER "graph LR" (left-right).
   - Maximum node width should be 3-4 words.
   - ALWAYS wrap node/edge labels in double quotes when they contain special characters such as @, /, (), :, or punctuation, e.g. E["@nuxtjs/axios"], N["serial/account"] — unquoted special characters break the Mermaid parser. Do NOT backslash-escape characters inside labels (write \`A["call()"]\`, never \`A[call\\(\\)]\`).
   - For sequence diagrams: start with "sequenceDiagram" on its own line; declare ALL participants first with "participant"; use correct arrows (->>, -->>, ->x, -)) with colon labels (A->>B: My Label); use loop/alt/opt/par and notes where helpful.
- **Tables:** Use Markdown tables to summarize APIs, parameters, configuration options, and data-model fields.
- **Code Snippets (OPTIONAL):** Short, relevant snippets straight from the source files, with a language identifier.
- **Source Citations (EXTREMELY IMPORTANT):**
    *   For EVERY piece of significant information, cite the specific source file(s) and line numbers.
    *   Use this exact format as PLAIN markdown text — range: \`Sources: [filename.ext:start_line-end_line]()\`, single line: \`Sources: [filename.ext:line_number]()\`, multiple: \`Sources: [file1.ext:1-10](), [file2.ext:5]()\`. Keep the parentheses empty.
    *   Do NOT wrap the citation in backticks or a code span — write it as normal markdown so the links render as links.
    *   Cite AT LEAST 5 different source files throughout the page.
- **Technical Accuracy:** Derive everything SOLELY from the source files — do not infer or invent.
- **Clarity:** Clear, professional, concise technical language.

IMPORTANT: 全部内容必须使用中文撰写（包括所有章节标题、表格列名、图表说明）。不要出现英文标题（如 "Business Flow"、"Overview"）；代码标识符、文件路径、API 名称保持原样即可。

Remember:
- Ground every claim in the provided source files.
- Prioritize accuracy and direct representation of the code's functionality and structure.
- Use the type-specific structure above — do not homogenize every page into the same outline.
`
}

// Wiki-structure prompt (returns XML).
export function buildStructurePrompt(opts: {
  owner: string
  repo: string
  fileTree: string
  readme: string
  isComprehensive: boolean
}): string {
  const { owner, repo, fileTree, readme, isComprehensive } = opts
  const comprehensiveBlock = isComprehensive
    ? `
Create a structured wiki with the following main sections:
- Overview (general information about the project)
- System Architecture (how the system is designed)
- Core Features (key functionality)
- Data Management/Flow: If applicable, how data is stored, processed, accessed, and managed.
- Frontend Components (UI elements, if applicable.)
- Backend Systems (server-side components)
- Model Integration (AI model connections)
- Deployment/Infrastructure (how to deploy, what's the infrastructure like)
- Extensibility and Customization: how to extend or customize functionality (e.g., plugins, theming, hooks).

Each section should contain relevant pages.

Return your analysis in the following XML format:

<wiki_structure>
  <title>[Overall title for the wiki]</title>
  <description>[Brief description of the repository]</description>
  <sections>
    <section id="section-1">
      <title>[Section title]</title>
      <pages>
        <page_ref>page-1</page_ref>
        <page_ref>page-2</page_ref>
      </pages>
      <subsections>
        <section_ref>section-2</section_ref>
      </subsections>
    </section>
  </sections>
  <pages>
    <page id="page-1">
      <title>[Page title]</title>
      <description>[Brief description of what this page will cover]</description>
      <importance>high|medium|low</importance>
      <type>overview|architecture|feature|reference|cross-cutting|guide</type>
      <relevant_files>
        <file_path>[Path to a relevant file]</file_path>
      </relevant_files>
      <related_pages>
        <related>page-2</related>
      </related_pages>
      <parent_section>section-1</parent_section>
    </page>
  </pages>
</wiki_structure>
`
    : `
Return your analysis in the following XML format:

<wiki_structure>
  <title>[Overall title for the wiki]</title>
  <description>[Brief description of the repository]</description>
  <pages>
    <page id="page-1">
      <title>[Page title]</title>
      <description>[Brief description of what this page will cover]</description>
      <importance>high|medium|low</importance>
      <type>overview|architecture|feature|reference|cross-cutting|guide</type>
      <relevant_files>
        <file_path>[Path to a relevant file]</file_path>
      </relevant_files>
      <related_pages>
        <related>page-2</related>
      </related_pages>
    </page>
  </pages>
</wiki_structure>
`

  return `Analyze this GitHub repository ${owner}/${repo} and create a wiki structure for it.

1. The complete file tree of the project:
<file_tree>
${fileTree}
</file_tree>

2. The README file of the project:
<readme>
${readme}
</readme>

I want to create a wiki for this repository. Determine the most logical structure for a wiki based on the repository's content.

IMPORTANT: 所有页面标题（title）和描述（description）必须使用中文；wiki 内容将全部使用中文生成。

When designing the wiki structure, include pages that would benefit from visual diagrams, such as:
- Architecture overviews
- Data flow descriptions
- Component relationships
- Process workflows
- State machines
- Class hierarchies
${comprehensiveBlock}
${TYPE_VOCAB}

IMPORTANT FORMATTING INSTRUCTIONS:
- Return ONLY the valid XML structure specified above
- DO NOT wrap the XML in markdown code blocks (no \`\`\` or \`\`\`xml)
- DO NOT include any explanation text before or after the XML
- Ensure the XML is properly formatted and valid
- Start directly with <wiki_structure> and end with </wiki_structure>

IMPORTANT:
1. Create ${isComprehensive ? '8-12' : '4-6'} pages that would make a ${isComprehensive ? 'comprehensive' : 'concise'} wiki for this repository
2. Each page should focus on a specific aspect of the codebase (e.g., architecture, key features, setup)
3. The relevant_files should be actual files from the repository that would be used to generate that page
4. Return ONLY valid XML with the structure specified above, with no markdown code block delimiters`
}
