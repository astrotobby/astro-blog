const fs = require('fs');
const path = require('path');

const BLOG_DIR = path.join(__dirname, '../src/content/blog');

function slugify(text) {
    return text
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
}

function fixFile(filePath) {
    const fileName = path.basename(filePath);
    if (!fileName.endsWith('.md')) return;

    const content = fs.readFileSync(filePath, 'utf8');

    if (!content.trim()) {
        console.log(`Deleting empty file: ${filePath}`);
        fs.unlinkSync(filePath);
        return;
    }

    // Basic check for frontmatter
    if (!content.startsWith('---')) {
        console.log(`Warning: No frontmatter found in ${fileName}. Deleting to prevent build failure.`);
        fs.unlinkSync(filePath);
        return;
    }

    const match = content.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)/);
    if (!match) {
        console.log(`Warning: Malformed frontmatter in ${fileName}. Deleting to prevent build failure.`);
        fs.unlinkSync(filePath);
        return;
    }

    const frontmatter = match[1];
    const body = match[2];

    const lines = frontmatter.split('\n');
    const fm = {};
    lines.forEach(line => {
        const colonIndex = line.indexOf(':');
        if (colonIndex !== -1) {
            const key = line.slice(0, colonIndex).trim().toLowerCase();
            const val = line.slice(colonIndex + 1).trim().replace(/^['"]|['"]$/g, '');
            fm[key] = val;
        }
    });

    // Check for required fields based on src/content.config.ts
    const requiredFields = ['title', 'description', 'pubdate'];
    const missingFields = requiredFields.filter(field => !fm[field]);

    if (missingFields.length > 0) {
        console.log(`Warning: Missing required fields (${missingFields.join(', ')}) in ${fileName}. Attempting to fill with defaults.`);
        if (!fm.title) fm.title = fileName.replace('.md', '');
        if (!fm.description) fm.description = fm.title;
        if (!fm.pubdate) fm.pubdate = new Date().toISOString().split('T')[0];
    }

    // Clean up body (remove AI-generated boilerplate)
    let cleanBody = body.replace(/^(Here is|Sure|I have generated|This is|Title:).*?\n/i, '').trim();
    
    // Reconstruct
    let newContent = '---\n';
    for (const [key, value] of Object.entries(fm)) {
        if (key === 'title') {
            newContent += `title: "${value}"\n`;
        } else {
            newContent += `${key}: "${value}"\n`;
        }
    }
    newContent += '---\n\n' + cleanBody;

    fs.writeFileSync(filePath, newContent);

    // Rename if necessary
    const dateMatch = fileName.match(/^(\d{4}-\d{2}-\d{2}-)/);
    const datePrefix = dateMatch ? dateMatch[1] : '';
    const slug = slugify(fm.title);
    const newFileName = slug.startsWith(datePrefix.replace(/-$/, '')) ? `${slug}.md` : `${datePrefix}${slug}.md`;
    const newPath = path.join(BLOG_DIR, newFileName);

    if (filePath !== newPath) {
        if (fs.existsSync(newPath)) {
            console.log(`Conflict: ${newFileName} already exists. Removing ${fileName}`);
            fs.unlinkSync(filePath);
        } else {
            console.log(`Renaming: ${fileName} -> ${newFileName}`);
            fs.renameSync(filePath, newPath);
        }
    }
}

if (fs.existsSync(BLOG_DIR)) {
    const files = fs.readdirSync(BLOG_DIR);
    files.forEach(file => fixFile(path.join(BLOG_DIR, file)));
} else {
    console.log('Blog directory not found.');
}
