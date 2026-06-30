// Generation prompts ported verbatim from src/app/[owner]/[repo]/page.tsx and the
// slides/workshop pages.
import { languageLabel } from '~/utils/repo'

// Workshop markdown prompt (ported from workshop/page.tsx).
export function buildWorkshopPrompt(opts: {
  owner: string
  repo: string
  wikiContent: string
  language: string
}): string {
  const { owner, repo, wikiContent, language } = opts
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

Make the workshop content in ${languageLabel(language)} language.`
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

// Page-content prompt. `filePathsList` is the pre-built markdown list of source
// files (e.g. "- [path](url)\n- ...").
export function buildPagePrompt(opts: {
  pageTitle: string
  filePathsList: string
  language: string
}): string {
  const { pageTitle, filePathsList, language } = opts
  return `You are an expert technical writer and software architect.
Your task is to generate a comprehensive and accurate technical wiki page in Markdown format about a specific feature, system, or module within a given software project.

You will be given:
1. The "[WIKI_PAGE_TOPIC]" for the page you need to create.
2. A list of "[RELEVANT_SOURCE_FILES]" from the project that you MUST use as the sole basis for the content. You have access to the full content of these files. You MUST use AT LEAST 5 relevant source files for comprehensive coverage - if fewer are provided, search for additional related files in the codebase.

CRITICAL STARTING INSTRUCTION:
The very first thing on the page MUST be a \`<details>\` block listing ALL the \`[RELEVANT_SOURCE_FILES]\` you used to generate the content. There MUST be AT LEAST 5 source files listed - if fewer were provided, you MUST find additional related files to include.
Format it exactly like this:
<details>
<summary>Relevant source files</summary>

Remember, do not provide any acknowledgements, disclaimers, apologies, or any other preface before the \`<details>\` block. JUST START with the \`<details>\` block.
The following files were used as context for generating this wiki page:

${filePathsList}
<!-- Add additional relevant files if fewer than 5 were provided -->
</details>

Immediately after the \`<details>\` block, the main title of the page should be a H1 Markdown heading: \`# ${pageTitle}\`.

Based ONLY on the content of the \`[RELEVANT_SOURCE_FILES]\`:

1.  **Introduction:** Start with a concise introduction (1-2 paragraphs) explaining the purpose, scope, and high-level overview of "${pageTitle}" within the context of the overall project. If relevant, and if information is available in the provided files, link to other potential wiki pages using the format \`[Link Text](#page-anchor-or-id)\`.

2.  **Detailed Sections:** Break down "${pageTitle}" into logical sections using H2 (\`##\`) and H3 (\`###\`) Markdown headings. For each section:
    *   Explain the architecture, components, data flow, or logic relevant to the section's focus, as evidenced in the source files.
    *   Identify key functions, classes, data structures, API endpoints, or configuration elements pertinent to that section.

3.  **Mermaid Diagrams:**
    *   EXTENSIVELY use Mermaid diagrams (e.g., \`flowchart TD\`, \`sequenceDiagram\`, \`classDiagram\`, \`erDiagram\`, \`graph TD\`) to visually represent architectures, flows, relationships, and schemas found in the source files.
    *   Ensure diagrams are accurate and directly derived from information in the \`[RELEVANT_SOURCE_FILES]\`.
    *   Provide a brief explanation before or after each diagram to give context.
    *   CRITICAL: All diagrams MUST follow strict vertical orientation:
       - Use "graph TD" (top-down) directive for flow diagrams
       - NEVER use "graph LR" (left-right)
       - Maximum node width should be 3-4 words
       - For sequence diagrams:
         - Start with "sequenceDiagram" directive on its own line
         - Define ALL participants at the beginning using "participant" keyword
         - Use the correct Mermaid arrow syntax (->>, -->>, ->x, -)) with colons for labels: A->>B: My Label
         - Use structural elements (loop/alt/opt/par) and notes where helpful

4.  **Tables:**
    *   Use Markdown tables to summarize key features, API parameters, configuration options, and data model fields.

5.  **Code Snippets (ENTIRELY OPTIONAL):**
    *   Include short, relevant code snippets directly from the \`[RELEVANT_SOURCE_FILES]\` with appropriate language identifiers.

6.  **Source Citations (EXTREMELY IMPORTANT):**
    *   For EVERY piece of significant information, you MUST cite the specific source file(s) and relevant line numbers.
    *   Use the exact format: \`Sources: [filename.ext:start_line-end_line]()\` for a range, or \`Sources: [filename.ext:line_number]()\` for a single line. Multiple files: \`Sources: [file1.ext:1-10](), [file2.ext:5]()\`.
    *   You MUST cite AT LEAST 5 different source files throughout the wiki page.

7.  **Technical Accuracy:** All information must be derived SOLELY from the \`[RELEVANT_SOURCE_FILES]\`. Do not infer or invent.

8.  **Clarity and Conciseness:** Use clear, professional, and concise technical language suitable for other developers.

9.  **Conclusion/Summary:** End with a brief summary paragraph if appropriate for "${pageTitle}".

IMPORTANT: Generate the content in ${languageLabel(language)} language.

Remember:
- Ground every claim in the provided source files.
- Prioritize accuracy and direct representation of the code's functionality and structure.
- Structure the document logically for easy understanding by other developers.
`
}

// Wiki-structure prompt (returns XML).
export function buildStructurePrompt(opts: {
  owner: string
  repo: string
  fileTree: string
  readme: string
  language: string
  isComprehensive: boolean
}): string {
  const { owner, repo, fileTree, readme, language, isComprehensive } = opts
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

IMPORTANT: The wiki content will be generated in ${languageLabel(language)} language.

When designing the wiki structure, include pages that would benefit from visual diagrams, such as:
- Architecture overviews
- Data flow descriptions
- Component relationships
- Process workflows
- State machines
- Class hierarchies
${comprehensiveBlock}
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
