class NarratorService {
    constructor() {
        this.synth = window.speechSynthesis;
        this.activeUtterance = null;
        this.voicePreferences = [
            'Natural',
            'Neural',
            'Siri',
            'Samantha',
            'Karen',
            'Moira',
            'Daniel',
            'Google US English',
            'Google UK English Female',
        ];
        // Warm up voices
        if (this.synth) {
            this.synth.getVoices();
        }
    }

    chooseBestVoice() {
        if (!this.synth) return null;
        const voices = this.synth.getVoices() || [];
        if (!voices.length) return null;

        const englishVoices = voices.filter(v => {
            const lang = (v.lang || '').toLowerCase();
            return lang.startsWith('en-us') || lang.startsWith('en-');
        });
        const candidateVoices = englishVoices.length ? englishVoices : voices;

        let selected = null;
        for (const pref of this.voicePreferences) {
            selected = candidateVoices.find(v => (v.name || '').includes(pref));
            if (selected) return selected;
        }
        selected = candidateVoices.find(v => (v.lang || '').toLowerCase().startsWith('en-us'));
        if (selected) return selected;
        selected = candidateVoices.find(v => (v.lang || '').toLowerCase().startsWith('en-'));
        return selected || candidateVoices[0];
    }

    // A web-audio synthesized "Walkie Talkie" ping/squelch sound
    async playPing() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();

            osc.type = 'square';
            osc.frequency.setValueAtTime(800, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(300, ctx.currentTime + 0.1);
            
            gainNode.gain.setValueAtTime(0.5, ctx.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.1);

            osc.connect(gainNode);
            gainNode.connect(ctx.destination);

            osc.start();
            osc.stop(ctx.currentTime + 0.1);

            // Give it a brief moment before resolving
            return new Promise(resolve => setTimeout(resolve, 600));
        } catch (e) {
            console.warn("Could not play ping sound", e);
            return Promise.resolve();
        }
    }

    async speak(text, onEndCallback) {
        if (!this.synth) return;

        // Cancel anything currently playing
        this.synth.cancel();

        // Play the walkie talkie ping FIRST
        await this.playPing();

        this.activeUtterance = new SpeechSynthesisUtterance(text);
        this.activeUtterance.lang = 'en-US';
        // Less robotic defaults: near-natural speaking cadence.
        this.activeUtterance.rate = 0.96;
        this.activeUtterance.pitch = 1.02;
        this.activeUtterance.volume = 1.0;

        const selectedVoice = this.chooseBestVoice();
        if (selectedVoice) {
            this.activeUtterance.voice = selectedVoice;
        }

        this.activeUtterance.onend = () => {
            if (onEndCallback) onEndCallback();
            this.activeUtterance = null;
        };
        
        this.activeUtterance.onerror = (e) => {
            console.error('Narrator error:', e);
            if (onEndCallback) onEndCallback();
            this.activeUtterance = null;
        };

        this.synth.speak(this.activeUtterance);
    }

    pause() {
        if (this.synth && this.synth.speaking && !this.synth.paused) {
            this.synth.pause();
        }
    }

    resume() {
        if (this.synth && this.synth.paused) {
            this.synth.resume();
        }
    }

    cancel() {
        if (this.synth) {
            this.synth.cancel();
            this.activeUtterance = null;
        }
    }

    isSpeaking() {
        return this.synth ? this.synth.speaking : false;
    }
}

export const narrator = new NarratorService();
