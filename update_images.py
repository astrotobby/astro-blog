import os
import re

replacements = {
    "AI vs Humans  Who Will Be Smarter in 10 Years": "/ai-vs-humans.jpg",
    "GitHub Copilot Shifts to Per-Token Pricing  What D": "/github-copilot-pricing.jpg",
    "Why 2026 is the Year of the Multiagent System (MAS": "/multiagent-systems.jpg",
    "Best Open-Source AI Agent Frameworks in 2026  A Pr": "/open-source-agents.jpg",
    "Why 2026 is the Breakthrough Year for Multi-Agent": "/breakthrough-year.jpg",
    "Beyond Chatbots  Why 2026 is the Year of Autonomou": "/beyond-chatbots.jpg",
    "LLM Benchmarks in 2026  Why Raw Scores Are Lying t": "/llm-benchmarks.jpg",
    "The LLM Benchmark Lie  Choosing the Best AI Model": "/llm-benchmarks.jpg",
    "Prompt Engineering in 2026  Advanced Techniques to": "/prompt-engineering.jpg",
    "Top Multi-Agent AI Frameworks for Developers in 20": "/multiagent-systems.jpg",
    "AI Coding Agents in 2026  The Quiet Revolution Mak": "/ai-coding-agents.jpg",
    "The AI Automation Tools Everyone Is Secretly Switc": "/ai-automation-tools.jpg",
    "The AI Shift Nobody Saw Coming in 2026  Why “Invis": "/ai-shift.jpg",
    "AI-Generated Video Is No Longer a Tool — It's a Ta": "/ai-video-tools.jpg",
    "The Free AI Video Generators Secretly Dominating 2": "/ai-video-tools.jpg",
    "The Post-Sora Gold Rush  5 High-Quality AI Video T": "/ai-video-tools.jpg",
    "The  Ghost in the Machine   Why 2026 is the Year A": "/ghost-in-machine.jpg",
    "Beyond Prompting  The Rise of World Models and  Ph": "/world-models.jpg",
    "Beyond SEO  Why Answer Engine Optimization (AEO) i": "/answer-engine-optimization.jpg",
    "The App-less Future  How AI Agents Are Replacing Y": "/app-less-future.jpg",
    "The Invisible Hand of AI  Navigating Zero-Click Co": "/ai-shift.jpg",
    "Vibe Coding  The Intuitive Language Reshaping Deve": "/vibe-coding.jpg",
    "Meta’s TRIBE v2  When AI Starts Modeling the Human": "/meta-tribe.jpg",
    "The Orchestration Era  Why 2026 is the Year of Mul": "/orchestration-era.jpg"
}

blog_dir = "src/content/blog"
for filename in os.listdir(blog_dir):
    if filename.endswith(".md"):
        filepath = os.path.join(blog_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()
        
        updated = False
        for title_part, new_image in replacements.items():
            if title_part in content:
                content = content.replace('image: "/blog-placeholder-1.jpg"', f'image: "{new_image}"')
                updated = True
                break
        
        if updated:
            with open(filepath, 'w') as f:
                f.write(content)
