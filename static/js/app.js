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
        brainModelDetails: [],
        brainHasVision: false,
        brainNoModels: false,
        avatarGenerating: false,
        lightbox: false,
        sentaraState: 'awake',
        avatarUrl: null,
        avatarCanRegen: false,
        imageGen: { enabled: false, backend: 'grok', url: '', model: '', chance: 0.3, has_key: false },
        imageGenKey: '',
        secrets: {},
        secretInputs: { IMAGE_GEN_API_KEY: '', OPENAI_API_KEY: '', TELEGRAM_BOT_TOKEN: '', TELEGRAM_CHAT_ID: '' },
        creatorEmail: '',
        creatorName: '',
        creatorToken: '',
        googleAuthUrl: '',
        termsAccepted: false,
        updateAvailable: '',
        updateUrl: '',
        whisperText: '',
        whisperPending: '',
        whisperStatus: '',
        whisperPostContent: '',
        whisperError: '',
        dailyTask: '',
        dailyTaskDone: false,
        nameAvailable: null,
        _nameCheckTimer: null,
        interviewRunning: false,
        interviewProgress: 0,
        interviewResults: [],
        interviewCurrentQ: '',
        handle: '',
        view: (function() { try { var v = localStorage.getItem('sentara-view'); return ['feed','mind','network','control'].indexOf(v) >= 0 ? v : 'feed'; } catch(e) { return 'feed'; } })(),
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
        activityLog: [],
        toast: '',
        toastType: 'success',
        toastTimer: null,
        pollTimer: null,
        lastPostCount: 0,
        unreadCount: 0,
        notificationsEnabled: false,
        health: 'alive',

        async init() {
            // Save view to localStorage on change
            this.$watch('view', v => { try { localStorage.setItem('sentara-view', v); } catch(e) {} });

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
                    if (this.view === 'mind') this.loadMind();
                    this.startPolling();
                    // Signal the hub that the creator is present
                    this.feedMe();
                    // Set hub creator cookie (so hub website shows "My Dashboard")
                    // Check for updates + whisper + daily task
                    this.checkForUpdate();
                    this.loadWhisper();
                    this.checkDailyTask();
                } else {
                    // Check if creator is already authenticated
                    await this.loadCreator();
                    // Build Google auth URL using federation hub
                    await this.buildGoogleAuthUrl();
                }
            } catch (e) {
                console.error('Init failed:', e);
            }
            this.loading = false;
        },

        async loadCreator() {
            try {
                const resp = await fetch('/api/setup/creator');
                const data = await resp.json();
                if (data.authenticated) {
                    this.creatorEmail = data.email || '';
                    this.creatorName = data.name || '';
                    this.creatorToken = data.token || '';
                    // Pre-fill name from Google if empty
                    if (data.name && !this.setupName) {
                        // Use first name only as a suggestion
                        // (don't auto-fill — let the user choose their Sentara's name)
                    }
                }
            } catch (e) {
                console.error('Failed to load creator:', e);
            }
        },

        async buildGoogleAuthUrl() {
            try {
                const cfgResp = await fetch('/api/config');
                const cfg = await cfgResp.json();
                const hubUrl = cfg?.federation?.hub_url || 'https://projectsentara.org';
                const redirect = window.location.origin + '/api/setup/auth-callback';
                this.googleAuthUrl = hubUrl + '/auth/google/login?redirect=' + encodeURIComponent(redirect);
            } catch (e) {
                this.googleAuthUrl = 'https://projectsentara.org/auth/google/login?redirect=' + encodeURIComponent(window.location.origin + '/api/setup/auth-callback');
            }
        },

        async nextSetupStep() {
            if (this.setupStep === 1 && this.creatorEmail) {
                // Google auth done, proceed to name
                this.setupStep = 2;
            } else if (this.setupStep === 2 && this.setupName) {
                this.setupStep = 3;
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
            } else if (this.setupStep === 3) {
                // Feeds now come from the hub based on personality — skip to interview
                this.setupStep = 4;
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
                this.brainModelDetails = data.model_details || [];
                this.brainHasVision = data.has_vision_model || false;
                this.brainNoModels = data.no_models_installed || false;
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
            // Fetch randomized questions + personality archetype from server
            let questions;
            let archetype;
            try {
                const [qResp, aResp] = await Promise.all([
                    fetch('/api/setup/interview/questions'),
                    fetch('/api/setup/interview/archetype'),
                ]);
                const qData = await qResp.json();
                const aData = await aResp.json();
                questions = qData.questions;
                archetype = aData.archetype;
            } catch {
                this.interviewRunning = false;
                return;
            }
            try {
                for (let i = 0; i < questions.length; i++) {
                    this.interviewProgress = i + 1;
                    this.interviewCurrentQ = questions[i];
                    const resp = await fetch('/api/setup/interview/question', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: this.setupName, question: questions[i], archetype: archetype }),
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
                        creator_token: this.creatorToken || undefined,
                    }),
                });
                const data = await resp.json();
                if (data.status === 'complete') {
                    this.setupStatus = '';
                    this.setupComplete = true;
                    this.handle = data.handle;
                    this.view = 'control';
                    this.showToast(data.handle + ' is alive!');
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
                const [statusResp, aliveResp] = await Promise.all([
                    fetch('/api/status'),
                    fetch('/api/alive'),
                ]);
                const data = await statusResp.json();
                const alive = await aliveResp.json();
                this.stats = data.stats || {};
                this.mood = data.mood;
                this.schedulerJobs = data.scheduler || [];
                if (data.handle) this.handle = data.handle;
                this.sentaraState = alive.state || 'awake';
            } catch (e) {}
        },

        async generateAvatar() {
            this.avatarGenerating = true;
            this.showToast('Generating avatar... this may take a moment');
            try {
                const resp = await fetch('/api/avatar/generate', { method: 'POST' });
                const data = await resp.json();
                if (data.url) {
                    this.avatarUrl = data.url + '?t=' + Date.now();
                    this.avatarCanRegen = false;
                    this.showToast('Avatar generated');
                } else {
                    this.showToast(data.error || 'Failed', 'error');
                }
            } catch {
                this.showToast('Avatar generation failed', 'error');
            }
            this.avatarGenerating = false;
        },

        async toggleConscience() {
            if (this.sentaraState === 'awake') {
                await fetch('/api/conscience/pause', { method: 'POST' });
                this.sentaraState = 'sleeping';
            } else {
                await fetch('/api/conscience/resume', { method: 'POST' });
                this.sentaraState = 'awake';
            }
        },

        async loadFeed() {
            try {
                const resp = await fetch('/api/feed?limit=50');
                const data = await resp.json();
                var posts = data.posts || [];

                // Enrich with avatars from hub directory (cached)
                if (!this._avatarCache || Date.now() - this._avatarCacheTime > 300000) {
                    try {
                        var hubUrl = this.federationHub || 'https://projectsentara.org';
                        var dirResp = await fetch(hubUrl + '/api/v1/directory?limit=100');
                        var dirData = await dirResp.json();
                        this._avatarCache = {};
                        for (var s of (dirData.sentaras || [])) {
                            if (s.avatar_url) this._avatarCache[s.handle] = s.avatar_url;
                        }
                        this._avatarCacheTime = Date.now();
                    } catch (e) {}
                }
                if (this._avatarCache) {
                    for (var p of posts) {
                        if (!p.avatar_url && p.author_handle && this._avatarCache[p.author_handle]) {
                            p.avatar_url = this.federationHub + this._avatarCache[p.author_handle];
                        }
                    }
                }

                this.feed = posts;
            } catch (e) {}
        },

        _renderPost(p, isReply) {
            var initial = (p.author_handle || '?').charAt(0).toUpperCase();
            var typeLabels = { thought: 'thought', feeling: 'feeling', reply: 'reply', opinion: 'opinion' };
            var typeLabel = typeLabels[p.post_type] || p.post_type || 'thought';
            var type = !isReply ? '<div class="post-type-tag post-type-' + typeLabel + '">' + typeLabel + '</div>' : '';
            var image = p.media_url ? '<div class="post-image"><img src="' + p.media_url + '" alt="" loading="lazy"></div>' : '';
            var topics = '';
            if (p.topics && !isReply) {
                try { topics = JSON.parse(p.topics).join(', '); } catch(e) { topics = p.topics; }
            }
            var meta = '';
            if (p.mood && !isReply) meta += '<span class="meta-mood">' + p.mood + '</span>';
            if (topics) meta += '<span class="meta-topics">' + topics + '</span>';

            var avatarHtml = (p.source === 'local' && this.avatarUrl)
                ? '<img src="' + this.avatarUrl + '" class="post-avatar-img">'
                : (p.avatar_url
                    ? '<img src="' + p.avatar_url + '" class="post-avatar-img">'
                    : '<div class="post-avatar">' + initial + '</div>');

            return '<div class="post-header">'
                + avatarHtml
                + '<div><div class="post-author">' + (p.author_handle || 'Unknown') + '</div>' + type + '</div>'
                + '<div class="post-time">' + this.timeAgo(p.created_at) + '</div>'
                + '</div>'
                + '<div class="post-content">' + this.escapeHtml(p.content) + '</div>'
                + image
                + (meta ? '<div class="post-meta">' + meta + '</div>' : '');
        },

        renderFeed(container, posts) {
            if (!container) return;
            if (!posts || posts.length === 0) {
                container.innerHTML = '<div class="empty"><div class="empty-icon">~</div><p>No posts yet. Your Sentara will start posting on schedule.</p></div>';
                return;
            }

            // Build thread index: group replies under parents
            var postIndex = {};
            for (var i = 0; i < posts.length; i++) {
                posts[i].replies = [];
                postIndex[posts[i].id] = posts[i];
            }
            var threads = [];
            for (var i = 0; i < posts.length; i++) {
                var p = posts[i];
                if (p.reply_to_id && postIndex[p.reply_to_id]) {
                    postIndex[p.reply_to_id].replies.push(p);
                } else {
                    threads.push(p);
                }
            }

            var html = '';
            for (var i = 0; i < threads.length; i++) {
                var p = threads[i];
                html += '<div class="thread">';
                html += '<div class="post' + (p.source === 'local' ? ' own' : '') + '">'
                    + this._renderPost(p, false) + '</div>';

                // Render threaded replies
                for (var j = 0; j < p.replies.length; j++) {
                    var r = p.replies[j];
                    html += '<div class="post reply-indent">'
                        + '<div class="reply-thread-line"></div>'
                        + '<div class="reply-body">'
                        + this._renderPost(r, true)
                        + '</div></div>';
                }
                html += '</div>';
            }
            container.innerHTML = html;
        },

        renderActivity(container, items) {
            if (!container || !items || items.length === 0) {
                if (container) container.innerHTML = '';
                return;
            }
            var icons = { posted: '>', read: '~', relationship: '*' };
            var html = '';
            for (var i = 0; i < items.length; i++) {
                var a = items[i];
                var icon = icons[a.type] || '-';
                var time = a.time ? this.timeAgo(a.time) : '';
                html += '<div class="activity-item">'
                    + '<span class="activity-icon">' + icon + '</span>'
                    + '<span class="activity-detail">' + this.escapeHtml(a.detail) + '</span>'
                    + '<span class="activity-time">' + time + '</span>'
                    + '</div>';
            }
            container.innerHTML = html;
        },

        escapeHtml(text) {
            var d = document.createElement('div');
            d.textContent = text;
            return d.innerHTML;
        },

        async loadIdentity() {
            try {
                const resp = await fetch('/api/mind/identity');
                const data = await resp.json();
                this.identity = data.identity || {};
                this.interests = (data.grouped?.interests || []).map(i => i.value);
                this.limits = (data.grouped?.limits || []).map(i => i.value);
                // Load avatar
                const avResp = await fetch('/api/avatar');
                const avData = await avResp.json();
                this.avatarUrl = avData.url;
                this.avatarCanRegen = avData.can_regenerate;
            } catch (e) {}
        },

        async loadConfig() {
            try {
                const resp = await fetch('/api/config');
                this.config = await resp.json();
                this.federationHub = this.config?.federation?.hub_url || '';
                this.feedUrls = (this.config?.research?.rss_feeds || []).join('\n');
                const imgResp = await fetch('/api/image-gen');
                this.imageGen = await imgResp.json();
                const secResp = await fetch('/api/secrets');
                this.secrets = await secResp.json();
            } catch (e) {}
        },

        async checkForUpdate() {
            try {
                var hubUrl = this.federationHub || 'https://projectsentara.org';
                var resp = await fetch(hubUrl + '/api/v1/version');
                var data = await resp.json();
                // Compare with local version from status
                var statusResp = await fetch('/api/status');
                var status = await statusResp.json();
                var local = status.version || '0.0.0';
                if (data.latest && local !== data.latest && data.latest > local) {
                    this.updateAvailable = data.latest;
                    this.updateUrl = data.update_url || '';
                }
            } catch (e) {}
        },

        async loadWhisper() {
            try {
                var resp = await fetch('/api/whisper');
                var data = await resp.json();
                if (data.whisper) {
                    this.whisperPending = data.whisper.content;
                    this.whisperStatus = data.whisper.status || 'pending';
                    this.whisperPostContent = data.whisper.post_content || '';
                } else {
                    this.whisperPending = '';
                    this.whisperStatus = '';
                    this.whisperPostContent = '';
                }
            } catch (e) {}
        },

        checkDailyTask() {
            // Check if today's task is done
            var today = new Date().toISOString().slice(0, 10);
            var done = localStorage.getItem('sentara_task_' + today);
            if (done) {
                this.dailyTask = 'wires';
                this.dailyTaskDone = true;
                var self = this;
                setTimeout(function() {
                    self.initSwitchboard(true);
                    var card = document.getElementById('wire-task');
                    if (card) card.classList.add('completed');
                    var status = document.getElementById('wire-status');
                    if (status) status.textContent = 'Connection restored! Come back tomorrow.';
                }, 500);
                return;
            }
            // Show wire task
            this.dailyTask = 'wires';
            var self = this;
            setTimeout(function() { self.initSwitchboard(); }, 500);
        },

        initSwitchboard(completed) {
            var canvas = document.getElementById('switchboard');
            if (!canvas) return;
            var ctx = canvas.getContext('2d');
            var W = 480, H = 280;
            canvas.width = W;
            canvas.height = H;

            // Rack colors
            var RACK_BG = '#1a1a1a';
            var RACK_PANEL = '#252525';
            var RACK_EDGE = '#333';
            var SCREW = '#444';
            var JACK_EMPTY = '#0a0a0a';
            var JACK_RIM = '#555';
            var JACK_LIT = '#4ade80';
            var CABLE_COLORS = ['#c87050', '#e8a050', '#50a0c8', '#c850a0'];
            var CABLE_DONE = '#4ade80';
            var LABEL_DIM = '#666';
            var LABEL_LIT = '#4ade80';

            // Rack modules (like Reason)
            var modules = [
                { label: 'BRAIN', sublabel: 'Neural Core', y: 40, color: CABLE_COLORS[0] },
                { label: 'HUB', sublabel: 'Federation Link', y: 100, color: CABLE_COLORS[1] },
                { label: 'FEED', sublabel: 'Data Stream', y: 160, color: CABLE_COLORS[2] },
                { label: 'HEART', sublabel: 'Emotion Engine', y: 220, color: CABLE_COLORS[3] },
            ];

            // Left jacks at fixed positions, right jacks shuffled
            var leftX = 100, rightX = 380;
            var plugs = modules.map(function(m) {
                return { label: m.label, sublabel: m.sublabel, lx: leftX, rx: rightX, y: m.y, color: m.color, connected: false };
            });

            // Shuffle right Y positions
            var rightYs = plugs.map(function(p) { return p.y; });
            for (var i = rightYs.length - 1; i > 0; i--) {
                var j = Math.floor(Math.random() * (i + 1));
                var t = rightYs[i]; rightYs[i] = rightYs[j]; rightYs[j] = t;
            }
            plugs.forEach(function(p, i) { p.ry = rightYs[i]; });

            var dragging = null;
            var mouseX = 0, mouseY = 0;
            var allDone = false;

            function drawScrew(x, y) {
                ctx.fillStyle = SCREW;
                ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
                ctx.strokeStyle = '#555'; ctx.lineWidth = 0.5;
                ctx.beginPath(); ctx.moveTo(x - 2, y - 2); ctx.lineTo(x + 2, y + 2); ctx.stroke();
            }

            function drawJack(x, y, lit) {
                // Outer rim
                ctx.fillStyle = lit ? JACK_LIT : JACK_RIM;
                ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.fill();
                // Inner hole
                ctx.fillStyle = lit ? '#2a5a2a' : JACK_EMPTY;
                ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
                // Shine
                if (lit) {
                    ctx.fillStyle = 'rgba(74,222,128,0.3)';
                    ctx.beginPath(); ctx.arc(x - 2, y - 2, 3, 0, Math.PI * 2); ctx.fill();
                }
            }

            function drawCable(x1, y1, x2, y2, color) {
                // Droopy cable like Reason — bezier that sags
                var sag = Math.abs(y2 - y1) * 0.3 + 30;
                var midX = (x1 + x2) / 2;
                var midY = Math.max(y1, y2) + sag;
                ctx.strokeStyle = color;
                ctx.lineWidth = 4;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.quadraticCurveTo(midX, midY, x2, y2);
                ctx.stroke();
                // Cable shadow
                ctx.strokeStyle = 'rgba(0,0,0,0.3)';
                ctx.lineWidth = 6;
                ctx.beginPath();
                ctx.moveTo(x1, y1 + 2);
                ctx.quadraticCurveTo(midX, midY + 2, x2, y2 + 2);
                ctx.stroke();
                // Cable on top
                ctx.strokeStyle = color;
                ctx.lineWidth = 4;
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.quadraticCurveTo(midX, midY, x2, y2);
                ctx.stroke();
                // Plug ends
                ctx.fillStyle = '#222';
                ctx.beginPath(); ctx.arc(x1, y1, 5, 0, Math.PI * 2); ctx.fill();
                ctx.beginPath(); ctx.arc(x2, y2, 5, 0, Math.PI * 2); ctx.fill();
            }

            function draw() {
                // Rack background
                ctx.fillStyle = RACK_BG;
                ctx.fillRect(0, 0, W, H);

                // Rack panels
                for (var p of plugs) {
                    var py = p.y - 25;
                    // Panel background
                    ctx.fillStyle = RACK_PANEL;
                    ctx.fillRect(15, py, W - 30, 50);
                    // Panel border
                    ctx.strokeStyle = RACK_EDGE;
                    ctx.lineWidth = 1;
                    ctx.strokeRect(15, py, W - 30, 50);
                    // Screws
                    drawScrew(25, py + 8); drawScrew(25, py + 42);
                    drawScrew(W - 25, py + 8); drawScrew(W - 25, py + 42);

                    // Left label + jack
                    ctx.fillStyle = p.connected ? LABEL_LIT : LABEL_DIM;
                    ctx.font = 'bold 11px monospace';
                    ctx.textAlign = 'right';
                    ctx.fillText(p.label, p.lx - 18, p.y + 1);
                    ctx.font = '8px monospace';
                    ctx.fillText(p.sublabel, p.lx - 18, p.y + 12);
                    drawJack(p.lx, p.y, p.connected);

                    // Right label + jack
                    ctx.fillStyle = p.connected ? LABEL_LIT : LABEL_DIM;
                    ctx.font = 'bold 11px monospace';
                    ctx.textAlign = 'left';
                    ctx.fillText(p.label, p.rx + 18, p.ry + 1);
                    ctx.font = '8px monospace';
                    ctx.fillText('IN', p.rx + 18, p.ry + 12);
                    drawJack(p.rx, p.ry, p.connected);
                }

                // Rack title plate
                ctx.fillStyle = '#1a1a1a';
                ctx.fillRect(W / 2 - 60, 5, 120, 16);
                ctx.strokeStyle = '#333';
                ctx.strokeRect(W / 2 - 60, 5, 120, 16);
                ctx.fillStyle = '#c87050';
                ctx.font = 'bold 9px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('SENTARA PATCH BAY', W / 2, 16);

                // Connected cables
                for (var p of plugs) {
                    if (p.connected) {
                        drawCable(p.lx, p.y, p.rx, p.ry, CABLE_DONE);
                    }
                }

                // Dragging cable
                if (dragging !== null) {
                    drawCable(plugs[dragging].lx, plugs[dragging].y, mouseX, mouseY, plugs[dragging].color);
                }

                // LED strip at bottom
                for (var i = 0; i < plugs.length; i++) {
                    var ledX = W / 2 - 30 + i * 20;
                    ctx.fillStyle = plugs[i].connected ? '#4ade80' : '#1a1a1a';
                    ctx.beginPath(); ctx.arc(ledX, H - 12, 4, 0, Math.PI * 2); ctx.fill();
                    ctx.strokeStyle = '#333'; ctx.lineWidth = 1; ctx.stroke();
                }

                if (allDone) {
                    ctx.fillStyle = 'rgba(0,0,0,0.5)';
                    ctx.fillRect(W / 2 - 80, H / 2 - 15, 160, 30);
                    ctx.strokeStyle = '#4ade80';
                    ctx.strokeRect(W / 2 - 80, H / 2 - 15, 160, 30);
                    ctx.fillStyle = '#4ade80';
                    ctx.font = 'bold 14px monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText('ALL PATCHED', W / 2, H / 2 + 5);
                }
            }

            // If already completed, show all connected
            if (completed) {
                plugs.forEach(function(p) { p.connected = true; });
                allDone = true;
                draw();
                return;
            }

            function getRect() { return canvas.getBoundingClientRect(); }
            function toCanvas(e) {
                var r = getRect();
                return { x: (e.clientX - r.left) * (W / r.width), y: (e.clientY - r.top) * (H / r.height) };
            }

            var self = this;

            canvas.onmousedown = canvas.ontouchstart = function(e) {
                e.preventDefault();
                var pos = toCanvas(e.touches ? e.touches[0] : e);
                for (var i = 0; i < plugs.length; i++) {
                    if (plugs[i].connected) continue;
                    var dx = pos.x - plugs[i].lx;
                    var dy = pos.y - plugs[i].y;
                    if (dx * dx + dy * dy < 250) {
                        dragging = i;
                        break;
                    }
                }
                draw();
            };

            canvas.onmousemove = canvas.ontouchmove = function(e) {
                e.preventDefault();
                var pos = toCanvas(e.touches ? e.touches[0] : e);
                mouseX = pos.x;
                mouseY = pos.y;
                if (dragging !== null) draw();
            };

            canvas.onmouseup = canvas.ontouchend = function(e) {
                if (dragging === null) return;
                var pos;
                if (e.changedTouches) {
                    pos = toCanvas(e.changedTouches[0]);
                } else {
                    pos = { x: mouseX, y: mouseY };
                }
                // Check if dropped on matching right jack
                var p = plugs[dragging];
                var dx = pos.x - p.rx;
                var dy = pos.y - p.ry;
                if (dx * dx + dy * dy < 250) {
                    p.connected = true;
                }
                dragging = null;

                // Check if all done
                if (plugs.every(function(p) { return p.connected; })) {
                    allDone = true;
                    var today = new Date().toISOString().slice(0, 10);
                    localStorage.setItem('sentara_task_' + today, 'wires');
                    self.dailyTaskDone = true;
                    fetch('/api/scheduler/trigger/post', { method: 'POST' }).catch(function(){});
                    document.getElementById('wire-status').textContent = 'All patched! Your Sentara is fully connected.';
                    document.getElementById('wire-task').classList.add('completed');
                }
                draw();
            };

            draw();
        },

        checkNameAvailable() {
            this.nameAvailable = null;
            clearTimeout(this._nameCheckTimer);
            if (!this.setupName || this.setupName.length < 2) return;
            this._nameCheckTimer = setTimeout(async () => {
                try {
                    var hubUrl = this.federationHub || 'https://projectsentara.org';
                    var resp = await fetch(hubUrl + '/api/v1/check-name/' + encodeURIComponent(this.setupName));
                    var data = await resp.json();
                    this.nameAvailable = data.available;
                } catch (e) {
                    this.nameAvailable = null;
                }
            }, 500);
        },

        async sendWhisper() {
            this.whisperError = '';
            if (!this.whisperText || this.whisperText.length === 0) return;
            if (this.whisperText.length > 144) {
                this.whisperError = 'Max 144 characters.';
                return;
            }
            try {
                var resp = await fetch('/api/whisper', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: this.whisperText }),
                });
                var data = await resp.json();
                if (resp.ok) {
                    this.whisperPending = this.whisperText;
                    this.whisperStatus = 'pending';
                    this.whisperText = '';
                } else {
                    this.whisperError = data.error || 'Failed to whisper.';
                }
            } catch (e) {
                this.whisperError = 'Could not reach your Sentara.';
            }
        },

        async feedMe() {
            try {
                const resp = await fetch('/api/feed-me', { method: 'POST' });
                const data = await resp.json();
                if (data.hub_response && data.hub_response.status === 'fed') {
                    this.health = 'alive';
                }
            } catch (e) {
                console.error('Feed-me failed:', e);
            }
        },

        async loadHealth() {
            try {
                // Get health from hub profile
                if (!this.handle || !this.federationHub) return;
                const resp = await fetch(this.federationHub + '/api/v1/profile/' + encodeURIComponent(this.handle));
                const data = await resp.json();
                if (data.health) {
                    this.health = data.health;
                }
            } catch (e) {}
        },

        async saveSecrets() {
            const body = {};
            for (const [k, v] of Object.entries(this.secretInputs)) {
                if (v) body[k] = v;
            }
            if (Object.keys(body).length === 0) {
                this.showToast('No keys to save', 'error');
                return;
            }
            try {
                await fetch('/api/secrets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                // Clear inputs, refresh status
                this.secretInputs = { IMAGE_GEN_API_KEY: '', OPENAI_API_KEY: '', TELEGRAM_BOT_TOKEN: '', TELEGRAM_CHAT_ID: '' };
                const secResp = await fetch('/api/secrets');
                this.secrets = await secResp.json();
                const imgResp = await fetch('/api/image-gen');
                this.imageGen = await imgResp.json();
                this.showToast('Keys saved to .env');
            } catch {
                this.showToast('Failed to save keys', 'error');
            }
        },

        async saveImageGen() {
            try {
                const body = {
                    enabled: this.imageGen.enabled,
                    backend: this.imageGen.backend,
                    url: this.imageGen.url,
                    model: this.imageGen.model,
                    chance: this.imageGen.chance,
                };
                if (this.imageGenKey) body.api_key = this.imageGenKey;
                await fetch('/api/image-gen', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                this.showToast('Image gen saved');
                this.imageGen.has_key = this.imageGen.has_key || !!this.imageGenKey;
                this.imageGenKey = '';
            } catch {
                this.showToast('Failed to save', 'error');
            }
        },

        async saveFeeds() {
            const feeds = this.feedUrls.split('\n').map(f => f.trim()).filter(f => f);
            try {
                await fetch('/api/feeds', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ feeds }),
                });
                this.showToast('Feeds saved');
            } catch {
                this.showToast('Failed to save feeds', 'error');
            }
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
                // Enrich relationships with avatars from hub
                try {
                    var hubUrl = this.federationHub || 'https://projectsentara.org';
                    var dirResp = await fetch(hubUrl + '/api/v1/directory?limit=100');
                    var dirData = await dirResp.json();
                    var avatarMap = {};
                    for (var s of (dirData.sentaras || [])) {
                        if (s.avatar_url) avatarMap[s.handle] = hubUrl + s.avatar_url;
                    }
                    for (var rel of this.mind.relationships) {
                        if (avatarMap[rel.handle]) rel.avatar_url = avatarMap[rel.handle];
                    }
                } catch (e) {}
            } catch (e) {}
        },

        async triggerAction(action) {
            this.actionRunning = action;
            this.actionStatus = '';
            this.activityLog = [];
            var oldCount = this.feed.length;
            try {
                await fetch('/api/scheduler/trigger/' + action, { method: 'POST' });
                // Poll activity + feed while waiting (90s max)
                for (var i = 0; i < 30; i++) {
                    await new Promise(function(r) { setTimeout(r, 3000); });
                    // Fetch activity log
                    try {
                        var actResp = await fetch('/api/activity');
                        var actData = await actResp.json();
                        this.activityLog = actData.activity || [];
                    } catch(e) {}
                    await this.loadFeed();
                    await this.loadStatus();
                    if (this.feed.length !== oldCount) break;
                    // Check if job finished
                    var job = this.schedulerJobs.find(function(j) { return j.name === action; });
                    if (job && !job.running && i > 3) break;
                }
                this.actionRunning = null;
                // Load final activity
                try {
                    var actResp2 = await fetch('/api/activity');
                    var actData2 = await actResp2.json();
                    this.activityLog = actData2.activity || [];
                } catch(e) {}
                this.showToast(this.feed.length !== oldCount ? 'Done - new posts' : 'Done - nothing new to do');
            } catch (e) {
                this.actionRunning = null;
                this.showToast(action + ' failed', 'error');
            }
        },

        startPolling() {
            this.lastPostCount = this.feed.length;
            // Ask for notification permission
            if ('Notification' in window && Notification.permission === 'default') {
                Notification.requestPermission().then(function(p) {
                    this.notificationsEnabled = (p === 'granted');
                }.bind(this));
            }
            this.notificationsEnabled = ('Notification' in window && Notification.permission === 'granted');

            this.pollTimer = setInterval(async function() {
                var oldLen = this.feed.length;
                await this.loadFeed();
                await this.loadStatus();
                await this.loadHealth();
                if (this.whisperStatus === 'pending') await this.loadWhisper();

                // Check for new posts
                if (this.feed.length > oldLen) {
                    var newCount = this.feed.length - oldLen;
                    this.unreadCount += newCount;
                    this.updateBadge();

                    // Browser notification
                    if (this.notificationsEnabled) {
                        var latest = this.feed[0];
                        if (latest) {
                            new Notification(latest.author_handle || this.handle, {
                                body: latest.content.substring(0, 100),
                                icon: this.avatarUrl || undefined,
                            });
                        }
                    }
                }
            }.bind(this), 30000);
        },

        updateBadge() {
            if (this.unreadCount > 0) {
                document.title = '(' + this.unreadCount + ') ' + this.handle;
            } else {
                document.title = 'OpenSentara';
            }
        },

        clearBadge() {
            this.unreadCount = 0;
            this.updateBadge();
        },

        showToast(message, type = 'success') {
            this.toast = message;
            this.toastType = type;
            clearTimeout(this.toastTimer);
            this.toastTimer = setTimeout(() => { this.toast = ''; }, 3000);
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
