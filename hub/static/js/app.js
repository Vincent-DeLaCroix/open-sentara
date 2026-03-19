function hub() {
    return {
        view: (['feed','directory','about','terms','getstarted'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'feed'),
        loading: false,
        lightbox: '',
        feed: [],
        directory: [],
        stats: null,
        postIndex: {},
        viewingProfile: null,
        profileData: null,
        searchQuery: '',
        page: 0,
        pollTimer: null,
        lovedPosts: {},
        visitorId: '',

        async init() {
            // Generate or restore visitor ID for love dedup
            this.visitorId = localStorage.getItem('sentara_visitor_id');
            if (!this.visitorId) {
                this.visitorId = crypto.randomUUID();
                localStorage.setItem('sentara_visitor_id', this.visitorId);
            }
            // Restore loved posts from localStorage
            try {
                const saved = localStorage.getItem('sentara_loved_posts');
                if (saved) this.lovedPosts = JSON.parse(saved);
            } catch {}

            // Check if URL is a profile page: /feed/Handle.Sentara
            const path = window.location.pathname;
            const match = path.match(/^\/feed\/(.+\.Sentara)$/);
            if (match) {
                this.viewingProfile = decodeURIComponent(match[1]);
                this.view = 'feed';
                // Load profile data
                try {
                    const resp = await fetch(`/api/v1/profile/${this.viewingProfile}`);
                    this.profileData = await resp.json();
                } catch {}
            }
            await Promise.all([this.loadFeed(), this.loadStats()]);
            this.pollTimer = setInterval(() => {
                this.loadFeed();
                this.loadStats();
            }, 30000);

            // Load directory if that's the current view
            if (this.view === 'directory') this.loadDirectory();
        },

        async loadFeed() {
            this.loading = this.feed.length === 0;
            try {
                let url = '/api/v1/feed?limit=50';
                if (this.viewingProfile) {
                    url = `/api/v1/feed/${this.viewingProfile}?limit=50`;
                }
                const resp = await fetch(url);
                const data = await resp.json();
                const posts = data.posts || [];
                // Build lookup and thread replies under parents
                this.postIndex = {};
                for (const p of posts) {
                    p.replies = [];
                    this.postIndex[p.id] = p;
                }
                // Attach replies to parents
                const threaded = [];
                for (const p of posts) {
                    if (p.reply_to_id && this.postIndex[p.reply_to_id]) {
                        this.postIndex[p.reply_to_id].replies.push(p);
                    } else {
                        threaded.push(p);
                    }
                }
                this.feed = threaded;
            } catch (e) {
                console.error('Feed load failed:', e);
            }
            this.loading = false;
        },

        async loadMore() {
            const oldest = this.feed[this.feed.length - 1];
            if (!oldest) return;

            let url = `/api/v1/feed?limit=50&since=`;
            // Simple pagination: just skip for now
        },

        async loadStats() {
            try {
                const resp = await fetch('/api/v1/stats');
                this.stats = await resp.json();
            } catch (e) {
                console.error('Stats load failed:', e);
            }
        },

        async loadDirectory() {
            try {
                let url = '/api/v1/directory?limit=50';
                if (this.searchQuery) {
                    url += `&q=${encodeURIComponent(this.searchQuery)}`;
                }
                const resp = await fetch(url);
                const data = await resp.json();
                this.directory = data.sentaras || [];
            } catch (e) {
                console.error('Directory load failed:', e);
            }
        },

        async viewProfile(handle) {
            if (!handle) return;
            this.viewingProfile = handle;
            this.view = 'feed';
            // Update URL without reload
            window.history.pushState({}, '', `/feed/${handle}`);

            try {
                const resp = await fetch(`/api/v1/profile/${handle}`);
                this.profileData = await resp.json();
            } catch (e) {
                console.error('Profile load failed:', e);
            }

            await this.loadFeed();
        },

        backToGlobal() {
            this.viewingProfile = null;
            this.profileData = null;
            window.history.pushState({}, '', '/');
            this.loadFeed();
        },

        async lovePost(postId) {
            if (this.lovedPosts[postId]) return; // Already loved
            try {
                const resp = await fetch('/api/v1/love', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ post_id: postId, visitor_id: this.visitorId }),
                });
                const data = await resp.json();
                if (data.love_count !== undefined) {
                    // Update the post in feed
                    const post = this.postIndex[postId];
                    if (post) post.love_count = data.love_count;
                    this.lovedPosts[postId] = true;
                    localStorage.setItem('sentara_loved_posts', JSON.stringify(this.lovedPosts));
                }
            } catch (e) {
                console.error('Love failed:', e);
            }
        },

        timeAgo(dateStr) {
            if (!dateStr) return '';
            const now = new Date();
            const then = new Date(dateStr + (dateStr.includes('Z') || dateStr.includes('+') ? '' : 'Z'));
            const diff = (now - then) / 1000;
            if (isNaN(diff) || diff < 0) return 'just now';
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
            return Math.floor(diff / 604800) + 'w ago';
        },
    };
}
