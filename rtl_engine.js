/**
 * Antigravity RTL Engine
 * Seamless Bidirectional (RTL / LTR) support for Google Antigravity.
 */
(function() {
    if (window.__antigravity_rtl_initialized) {
        return;
    }
    window.__antigravity_rtl_initialized = true;

    // Persian, Arabic, Hebrew, Urdu unicode character ranges
    const RTL_REGEX = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\u0590-\u05FF]/;

    // 1. Inject high-priority RTL and typography stylesheet
    function injectStyles() {
        const styleId = 'antigravity-rtl-injected-css';
        let style = document.getElementById(styleId);
        if (!style) {
            style = document.createElement('style');
            style.id = styleId;
            (document.head || document.documentElement).appendChild(style);
        }

        style.textContent = `
            /* Core RTL text styling */
            [dir="rtl"] {
                direction: rtl !important;
                text-align: right !important;
                line-height: 1.85 !important;
            }

            /* Optimized Persian typography fallback */
            [dir="rtl"], [dir="rtl"] p, [dir="rtl"] span, [dir="rtl"] li, [dir="rtl"] h1, [dir="rtl"] h2, [dir="rtl"] h3 {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Vazirmatn", "Shabnam", "Sahel", Tahoma, Arial, sans-serif;
            }

            /* Strictly preserve LTR on all code blocks, syntax highlighters & terminals */
            pre, pre *, code, code *, kbd, samp, .font-mono, [class*="font-mono"], [class*="terminal"] {
                direction: ltr !important;
                text-align: left !important;
                unicode-bidi: isolate !important;
            }

            /* Inline code and technical terms inside RTL blocks */
            [dir="rtl"] code, [dir="rtl"] .font-mono {
                display: inline-block !important;
                direction: ltr !important;
                unicode-bidi: isolate !important;
                padding: 1px 5px !important;
                margin: 0 2px !important;
                border-radius: 4px !important;
                vertical-align: baseline !important;
            }

            /* Lists and bullet points in RTL */
            ul[dir="rtl"], ol[dir="rtl"] {
                padding-right: 1.75rem !important;
                padding-left: 0.5rem !important;
                margin-right: 0 !important;
                list-style-position: outside !important;
            }

            li[dir="rtl"] {
                text-align: right !important;
            }

            /* Input box and textareas auto direction */
            [contenteditable="true"], textarea, input[type="text"] {
                unicode-bidi: plaintext !important;
            }

            /* Blockquotes in RTL */
            blockquote[dir="rtl"] {
                border-right: 3px solid currentColor !important;
                border-left: none !important;
                padding-right: 1rem !important;
                padding-left: 0 !important;
            }

            /* Tables in RTL */
            table[dir="rtl"] th, table[dir="rtl"] td {
                text-align: right !important;
            }
        `;
    }

    // 2. Element processor
    function processElement(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) return;

        // Skip code containers and non-text elements
        if (el.closest('pre') || el.matches('pre, code, script, style, svg, path, iframe')) {
            return;
        }

        // Input controls
        if (el.matches('textarea, input[type="text"], [contenteditable="true"]')) {
            if (el.getAttribute('dir') !== 'auto') {
                el.setAttribute('dir', 'auto');
            }
            return;
        }

        // Content blocks
        const isBlock = el.matches('p, li, h1, h2, h3, h4, h5, h6, blockquote, .cursor-pointer, [class*="select-text"], [class*="message"]');
        if (isBlock) {
            const text = el.textContent || '';
            if (RTL_REGEX.test(text)) {
                if (el.getAttribute('dir') !== 'auto') {
                    el.setAttribute('dir', 'auto');
                }
                // When an LI is RTL, ensure its parent list displays bullets/numbers on the right
                if (el.tagName === 'LI' && el.parentElement) {
                    if (el.parentElement.getAttribute('dir') !== 'rtl') {
                        el.parentElement.setAttribute('dir', 'rtl');
                    }
                }
            }
        }
    }

    // 3. Scan a DOM subtree
    function scanSubtree(root) {
        if (!root || !root.querySelectorAll) return;
        const targets = root.querySelectorAll('p, li, h1, h2, h3, h4, h5, h6, blockquote, textarea, input, [contenteditable], .cursor-pointer, [class*="select-text"]');
        for (let i = 0; i < targets.length; i++) {
            processElement(targets[i]);
        }
    }

    // 4. Initialization & MutationObserver
    function init() {
        injectStyles();
        if (document.body) {
            scanSubtree(document.body);
        }

        let scheduled = false;
        const pendingNodes = new Set();

        const observer = new MutationObserver((mutations) => {
            for (let i = 0; i < mutations.length; i++) {
                const m = mutations[i];
                if (m.type === 'childList') {
                    for (let j = 0; j < m.addedNodes.length; j++) {
                        const node = m.addedNodes[j];
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            pendingNodes.add(node);
                        }
                    }
                } else if (m.type === 'characterData') {
                    const parent = m.target.parentElement;
                    if (parent) pendingNodes.add(parent);
                }
            }

            if (!scheduled && pendingNodes.size > 0) {
                scheduled = true;
                requestAnimationFrame(() => {
                    scheduled = false;
                    for (const node of pendingNodes) {
                        processElement(node);
                        scanSubtree(node);
                    }
                    pendingNodes.clear();
                });
            }
        });

        const target = document.body || document.documentElement;
        if (target) {
            observer.observe(target, {
                childList: true,
                subtree: true,
                characterData: true
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
