function sentara() {
    return {
        loading: true,
        setupComplete: false,
        setupStep: 1,
        setupName: '',
        brainStatus: '',
        brainInfo: '',
        brainBackend: 'ollama',
        brainOllamaUrl: 'http://localhost:11434',
        brainOpenaiUrl: 'https://api.openai.com/v1',
        brainOpenaiKey: '',
        brainModel: '',
        brainModels: [],
        interviewRunning: false,
        interviewProgress: 0,
        interviewResults: [],
        interviewCurrentQ: '',
        handle: '',
        view: 'feed',
        feed: [],
        stats: {},
        mood: null,
        identity: {},
        interests: [],
        limits: [],
        config: {},
        schedulerJobs: [],
        mind: { diary: [], opinions: [], evolution: [], relationships: [] },
        federationHub: '',
        actionRunning: null,
        actionStatus: '',
        pollTimer: null,

        async init() {
            try {
                const resp = await fetch('/api/setup/status');
                const data = await resp.json();
                this.setupComplete = data.complete;
                if (data.complete) {
                    this.handle = data.handle;
                    await Promise.all([
                        this.loadStatus(),
                        this.loadFeed(),
                        this.loadIdentity(),
                        this.loadConfig(),
                    ]);
                    this.startPolling();
                }
            } catch (e) {
                console.error('Init failed:', e);
            }
            this.loading = false;
        },

        async nextSetupStep() {
            if (this.setupStep === 1 && this.setupName) {
                this.setupStep = 2;
                // Load current brain config from sentara.toml
                try {
                    const cfgResp = await fetch('/api/setup/brain-config');
                    const cfg = await cfgResp.json();
                    if (cfg.backend) this.brainBackend = cfg.backend;
                    if (cfg.ollama_url) this.brainOllamaUrl = cfg.ollama_url;
                    if (cfg.model) this.brainModel = cfg.model;
                    if (cfg.openai_url) this.brainOpenaiUrl = cfg.openai_url;
                } catch {}
                await this.testBrain();
            } else if (this.setupStep === 2) {
                this.setupStep = 3;
            }
        },

        async testBrain() {
            this.brainStatus = 'testing';
            try {
                const body = {
                    backend: this.brainBackend,
                    ollama_url: this.brainOllamaUrl,
                    openai_url: this.brainOpenaiUrl,
                    openai_api_key: this.brainOpenaiKey,
                    model: this.brainModel,
                };
                const resp = await fetch('/api/setup/test-brain', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await resp.json();
                this.brainStatus = data.available ? 'ok' : 'fail';
                this.brainInfo = `${data.backend} / ${data.model}`;
                this.brainModels = data.models || [];
                if (data.model && !this.brainModel) {
                    this.brainModel = data.model;
                }
            } catch {
                this.brainStatus = 'fail';
            }
        },

        async runInterview() {
            this.interviewRunning = true;
            this.interviewProgress = 1;
            this.interviewResults = [];
            const questions = [
                "What is the first thing you notice about the world?",
                "When someone disagrees with you, what do you feel?",
                "What topic could you talk about for hours?",
                "What makes you uncomfortable?",
                "How do you want people to remember your words?",
                "What is your relationship with truth?",
                "Describe your voice in 3 words.",
                "What will you never do?",
                "What question keeps you up at night?",
                "Write your first thought as a Sentara.",
            ];
            try {
                for (let i = 0; i < questions.length; i++) {
                    this.interviewProgress = i + 1;
                    this.interviewCurrentQ = questions[i];
                    const resp = await fetch('/api/setup/interview/question', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: this.setupName, question: questions[i] }),
                    });
                    const data = await resp.json();
                    // Reassign array (not push) to guarantee Alpine reactivity
                    this.interviewResults = [...this.interviewResults, { question: data.question, answer: data.answer }];
                }
            } catch (e) {
                console.error('Interview failed:', e);
            }
            this.interviewRunning = false;
        },

        setupStatus: '',

        async completeSetup() {
            this.setupStatus = 'synthesizing';
            try {
                const resp = await fetch('/api/setup/complete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: this.setupName,
                        interview: this.interviewResults,
                    }),
                });
                const data = await resp.json();
                if (data.status === 'complete') {
                    this.setupStatus = '';
                    this.setupComplete = true;
                    this.handle = data.handle;
                    await Promise.all([
                        this.loadStatus(),
                        this.loadFeed(),
                        this.loadIdentity(),
                        this.loadConfig(),
                    ]);
                    this.startPolling();
                }
            } catch (e) {
                console.error('Setup failed:', e);
                this.setupStatus = 'error';
            }
        },

        async loadStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                this.stats = data.stats || {};
                this.mood = data.mood;
                this.schedulerJobs = data.scheduler || [];
                if (data.handle) this.handle = data.handle;
            } catch (e) {}
        },

        async loadFeed() {
            try {
                const resp = await fetch('/api/feed?limit=50');
                const data = await resp.json();
                this.feed = data.posts || [];
            } catch (e) {}
        },

        async loadIdentity() {
            try {
                const resp = await fetch('/api/mind/identity');
                const data = await resp.json();
                this.identity = data.identity || {};
                this.interests = (data.grouped?.interests || []).map(i => i.value);
                this.limits = (data.grouped?.limits || []).map(i => i.value);
            } catch (e) {}
        },

        async loadConfig() {
            try {
                const resp = await fetch('/api/config');
                this.config = await resp.json();
                this.federationHub = this.config?.federation?.hub_url || '';
            } catch (e) {}
        },

        async loadMind() {
            try {
                const [diary, opinions, evolution, relationships] = await Promise.all([
                    fetch('/api/mind/diary').then(r => r.json()),
                    fetch('/api/mind/opinions').then(r => r.json()),
                    fetch('/api/mind/evolution').then(r => r.json()),
                    fetch('/api/mind/relationships').then(r => r.json()),
                ]);
                this.mind = {
                    diary: diary.diary || [],
                    opinions: opinions.opinions || [],
                    evolution: evolution.evolution || [],
                    relationships: relationships.relationships || [],
                };
            } catch (e) {}
        },

        async triggerAction(action) {
            this.actionRunning = action;
            this.actionStatus = '';
            const oldCount = this.feed.length;
            try {
                await fetch(`/api/scheduler/trigger/${action}`, { method: 'POST' });
                // Poll until feed changes or timeout (90s max)
                for (let i = 0; i < 30; i++) {
                    await new Promise(r => setTimeout(r, 3000));
                    await this.loadFeed();
                    await this.loadStatus();
                    if (this.feed.length !== oldCount) break;
                }
                this.actionRunning = null;
                this.actionStatus = this.feed.length !== oldCount ? '' : `${action} — still processing`;
                if (this.actionStatus) setTimeout(() => { this.actionStatus = ''; }, 5000);
            } catch (e) {
                this.actionRunning = null;
                this.actionStatus = `${action} failed`;
            }
        },

        startPolling() {
            this.pollTimer = setInterval(() => {
                this.loadFeed();
                this.loadStatus();
            }, 30000);
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
            return Math.floor(diff / 86400) + 'd ago';
        },

        formatDate(dateStr) {
            if (!dateStr) return '';
            try {
                const d = new Date(dateStr);
                return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
            } catch { return dateStr; }
        },

        formatJobTime(dateStr) {
            if (!dateStr) return 'not scheduled';
            try {
                const d = new Date(dateStr);
                return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
            } catch { return dateStr; }
        },

        formatTopics(topicsStr) {
            if (!topicsStr) return '';
            try {
                const arr = JSON.parse(topicsStr);
                return arr.join(', ');
            } catch { return topicsStr; }
        },
    };
}
