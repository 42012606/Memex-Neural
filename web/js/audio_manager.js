class AudioManagerImpl {
    constructor() {
        this.wakeLock = null;
        this.currentAudio = null;

        // Recording state
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.recordingStream = null;
        this.isRecording = false;
        this.recordingStartTime = null;
        this.onRecordingStateChange = null; // Callback for UI updates
    }

    // =====================
    // TTS Playback (Existing)
    // =====================
    async playText(text) {
        if (!text) return;

        // Stop previous if exists
        this.stop();

        await this.requestWakeLock();

        try {
            console.log("🔊 Synthesizing TTS:", text.slice(0, 20) + "...");
            const response = await fetch('/api/v1/audio/speak', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });

            if (!response.ok) throw new Error("TTS API Error");

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            this.currentAudio = new Audio(url);

            this.currentAudio.onended = () => {
                this.releaseWakeLock();
                URL.revokeObjectURL(url);
                this.currentAudio = null;
            };

            this.currentAudio.onerror = (e) => {
                console.error("Audio Playback Error:", e);
                this.releaseWakeLock();
            }

            await this.currentAudio.play();
        } catch (e) {
            console.error("TTS Failed:", e);
            this.releaseWakeLock();
        }
    }

    stop() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio = null;
        }
        this.releaseWakeLock();
    }

    // =====================
    // Voice Recording (New)
    // =====================

    /**
     * Start recording audio from microphone
     * @returns {Promise<boolean>} Success status
     */
    async startRecording() {
        if (this.isRecording) {
            console.warn('🎤 Already recording');
            return false;
        }

        try {
            // Request microphone access
            this.recordingStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    sampleRate: 16000
                }
            });

            // Determine best supported MIME type
            const mimeType = this.getSupportedMimeType();
            console.log('🎤 Using MIME type:', mimeType);

            this.audioChunks = [];
            this.mediaRecorder = new MediaRecorder(this.recordingStream, {
                mimeType: mimeType
            });

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                }
            };

            this.mediaRecorder.onerror = (event) => {
                console.error('🎤 MediaRecorder error:', event.error);
                this.stopRecording(true);
            };

            // Start recording
            this.mediaRecorder.start(100); // Collect data every 100ms
            this.isRecording = true;
            this.recordingStartTime = Date.now();

            await this.requestWakeLock();
            console.log('🎤 Recording started');

            // Notify UI
            if (this.onRecordingStateChange) {
                this.onRecordingStateChange(true, 0);
            }

            // Start duration tracker
            this._startDurationTracker();

            return true;
        } catch (error) {
            console.error('🎤 Failed to start recording:', error);
            this.cleanupRecording();

            // Check for permission denied
            if (error.name === 'NotAllowedError') {
                throw new Error('麦克风权限被拒绝，请在浏览器设置中允许访问麦克风');
            } else if (error.name === 'NotFoundError') {
                throw new Error('未检测到麦克风设备');
            }
            throw error;
        }
    }

    /**
     * Stop recording and return audio blob
     * @param {boolean} cancel - If true, discard the recording
     * @returns {Promise<Blob|null>} Audio blob or null if cancelled
     */
    async stopRecording(cancel = false) {
        if (!this.isRecording || !this.mediaRecorder) {
            console.warn('🎤 Not recording');
            return null;
        }

        return new Promise((resolve) => {
            this.mediaRecorder.onstop = () => {
                this._stopDurationTracker();

                if (cancel) {
                    console.log('🎤 Recording cancelled');
                    this.cleanupRecording();
                    resolve(null);
                    return;
                }

                // Check minimum duration (500ms)
                const duration = Date.now() - this.recordingStartTime;
                if (duration < 500) {
                    console.log('🎤 Recording too short, discarding');
                    this.cleanupRecording();
                    resolve(null);
                    return;
                }

                // Create audio blob
                const mimeType = this.getSupportedMimeType();
                const blob = new Blob(this.audioChunks, { type: mimeType });
                console.log('🎤 Recording stopped, blob size:', blob.size, 'bytes');

                this.cleanupRecording();
                resolve(blob);
            };

            // Stop the recorder
            if (this.mediaRecorder.state !== 'inactive') {
                this.mediaRecorder.stop();
            }
            this.isRecording = false;

            // Notify UI
            if (this.onRecordingStateChange) {
                this.onRecordingStateChange(false, 0);
            }
        });
    }

    /**
     * Cancel recording without saving
     */
    cancelRecording() {
        return this.stopRecording(true);
    }

    /**
     * Get recording duration in seconds
     */
    getRecordingDuration() {
        if (!this.recordingStartTime) return 0;
        return Math.floor((Date.now() - this.recordingStartTime) / 1000);
    }

    /**
     * Clean up recording resources
     */
    cleanupRecording() {
        if (this.recordingStream) {
            this.recordingStream.getTracks().forEach(track => track.stop());
            this.recordingStream = null;
        }
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.recordingStartTime = null;
        this.releaseWakeLock();
    }

    /**
     * Get supported MIME type for recording
     */
    getSupportedMimeType() {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4',
            'audio/wav'
        ];
        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }
        return 'audio/webm'; // Fallback
    }

    /**
     * Start tracking recording duration for UI updates
     */
    _startDurationTracker() {
        this._durationInterval = setInterval(() => {
            if (this.isRecording && this.onRecordingStateChange) {
                this.onRecordingStateChange(true, this.getRecordingDuration());
            }
        }, 1000);
    }

    /**
     * Stop duration tracker
     */
    _stopDurationTracker() {
        if (this._durationInterval) {
            clearInterval(this._durationInterval);
            this._durationInterval = null;
        }
    }

    // =====================
    // Wake Lock
    // =====================
    async requestWakeLock() {
        if ('wakeLock' in navigator) {
            try {
                this.wakeLock = await navigator.wakeLock.request('screen');
                console.log('💡 Wake Lock active');
            } catch (err) {
                console.warn('Wake Lock rejected:', err);
            }
        }
    }

    async releaseWakeLock() {
        if (this.wakeLock) {
            try {
                await this.wakeLock.release();
                this.wakeLock = null;
                console.log('💡 Wake Lock released');
            } catch (e) {
                console.log('Wake lock release error', e);
            }
        }
    }
}

window.AudioManager = new AudioManagerImpl();
