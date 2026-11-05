/**
 * Family Events Bottom Ticker Script
 * Automatically loads events from /api/events and renders a persistent marquee ticker bar.
 */

(function () {
    // Only run if DOM is ready
    function initTicker() {
        if (document.getElementById('family-event-ticker')) return;

        // Ensure stylesheet is loaded
        if (!document.querySelector('link[href*="ticker.css"]')) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = '/static/css/ticker.css';
            document.head.appendChild(link);
        }

        // Create Ticker Container
        const ticker = document.createElement('div');
        ticker.id = 'family-event-ticker';
        ticker.className = 'family-event-ticker';
        ticker.setAttribute('role', 'region');
        ticker.setAttribute('aria-label', 'Family events and milestones ticker');

        ticker.innerHTML = `
            <a class="ticker-badge-container" href="/calendar" title="Open Family Calendar">
                <span class="ticker-dot"></span>
                <span>Events</span>
            </a>
            <div class="ticker-track-wrapper">
                <div class="ticker-track" id="ticker-track">
                    <span style="color: #94a3b8; font-size: 0.8rem;">Loading family milestones &amp; events...</span>
                </div>
            </div>
            <a class="ticker-btn-calendar" href="/calendar">Open Calendar &rarr;</a>
        `;

        document.body.appendChild(ticker);

        loadTickerEvents();
    }

    async function loadTickerEvents() {
        const track = document.getElementById('ticker-track');
        if (!track) return;

        try {
            const response = await fetch('/api/events');
            const data = await response.json();
            const events = data.events || [];

            if (!events.length) {
                track.innerHTML = `
                    <span style="color: #94a3b8; font-size: 0.8rem;">
                        No upcoming events recorded yet. <a href="/calendar" style="color: #fde047; text-decoration: underline;">Add the first family event</a>!
                    </span>
                `;
                return;
            }

            // Format date for display
            function formatDisplayDate(dateStr) {
                if (!dateStr) return '';
                // If format is MM-DD
                const parts = dateStr.split('-');
                if (parts.length === 2) {
                    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                    const m = parseInt(parts[0], 10);
                    const d = parseInt(parts[1], 10);
                    if (m >= 1 && m <= 12) {
                        return `${months[m - 1]} ${d}`;
                    }
                } else if (parts.length === 3) {
                    const dateObj = new Date(dateStr);
                    if (!isNaN(dateObj.getTime())) {
                        return dateObj.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
                    }
                }
                return dateStr;
            }

            // Build HTML items
            const itemsHtml = events.map(ev => {
                const icon = ev.icon || (ev.type === 'birthday' ? '🎂' : ev.type === 'anniversary' ? '💍' : '📅');
                const dateText = formatDisplayDate(ev.date || ev.full_date);
                return `
                    <a class="ticker-item" href="/calendar" title="${ev.description || ev.title}">
                        <span class="ticker-item-icon">${icon}</span>
                        <span class="ticker-item-title">${ev.title}</span>
                        ${dateText ? `<span class="ticker-item-date">${dateText}</span>` : ''}
                    </a>
                `;
            }).join('');

            // Duplicate items to ensure smooth continuous marquee loop
            track.innerHTML = itemsHtml + itemsHtml;

            // Adjust animation duration based on count
            const duration = Math.max(25, events.length * 8);
            track.style.animationDuration = `${duration}s`;

        } catch (err) {
            track.innerHTML = `<span style="color: #94a3b8;">Family Milestones · <a href="/calendar" style="color: #fde047;">Open Calendar</a></span>`;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTicker);
    } else {
        initTicker();
    }
})();

