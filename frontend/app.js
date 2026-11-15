const navigation = document.querySelectorAll(".nav");
const pages = document.querySelectorAll(".page");

navigation.forEach(button => {

    button.addEventListener("click", () => {

        navigation.forEach(item =>
            item.classList.remove("active")
        );

        pages.forEach(page =>
            page.classList.remove("active")
        );

        button.classList.add("active");

        const page = button.dataset.page;

        document
            .getElementById(page)
            .classList.add("active");
    });

});


/* Script statistics */

const script = document.getElementById("script");
const wordsDisplay = document.getElementById("words");
const durationDisplay = document.getElementById("duration");

script.addEventListener("input", () => {

    const text = script.value.trim();

    const words = text
        ? text.split(/\s+/).length
        : 0;

    wordsDisplay.textContent = words;

    /*
        Narration estimate:
        approximately 150 words per minute
    */

    const minutes = words / 150;

    durationDisplay.textContent =
        minutes < 1
            ? minutes.toFixed(1)
            : Math.round(minutes);
});


/* Backend status */

async function checkServer() {

    const status =
        document.getElementById("serverStatus");

    try {

        const response =
            await fetch("/api/health");

        const data =
            await response.json();

        if (data.status === "ok") {
            status.textContent = "Studio online";
        }

    } catch {

        status.textContent = "Server unavailable";

    }

}

checkServer();

/* Pocket TTS integration */

const voiceSelect = document.getElementById("voice");
const generateBtn = document.getElementById("generateBtn");
const generationStatus = document.getElementById("generationStatus");
const audioResult = document.getElementById("audioResult");
const audioPlayer = document.getElementById("audioPlayer");
const downloadAudio = document.getElementById("downloadAudio");
const audioFilename = document.getElementById("audioFilename");
const generatedVoiceName = document.getElementById("generatedVoiceName");
const regenerateAudio = document.getElementById("regenerateAudio");

const longformMode =
    document.getElementById("longformMode");

const longformProgress =
    document.getElementById("longformProgress");

const longformStatusText =
    document.getElementById("longformStatusText");

const longformPercent =
    document.getElementById("longformPercent");

const longformProgressBar =
    document.getElementById("longformProgressBar");

const longformChunkText =
    document.getElementById("longformChunkText");

const longformCurrentText =
    document.getElementById("longformCurrentText");

const longformError =
    document.getElementById("longformError");

const longformSection =
    document.querySelector(".longform-section");

let currentLongformJobId = null;
let longformPollingTimer = null;

let savedVoices = [];
let activeVoiceCategory = "all";
let currentGeneratedAudioUrl = null;


async function loadVoices() {

    const response = await fetch("/api/voices");

    if (!response.ok) {
        throw new Error("Unable to load voice library.");
    }

    savedVoices = await response.json();

    const previousSelection = voiceSelect.value;

    voiceSelect.replaceChildren();

    savedVoices.forEach(voice => {

        const option = document.createElement("option");

        option.value = voice.id;
        option.textContent =
            `${voice.favorite ? "★ " : ""}${voice.name}`;

        voiceSelect.appendChild(option);
    });

    if (savedVoices.some(v => v.id === previousSelection)) {
        voiceSelect.value = previousSelection;
    }

    renderVoiceLibrary();
}


function renderVoiceLibrary() {

    const grid = document.getElementById("voiceGrid");
    grid.replaceChildren();

    const filtered = savedVoices.filter(voice => {

        if (activeVoiceCategory === "all") return true;

        if (activeVoiceCategory === "favorites") {
            return Boolean(voice.favorite);
        }

        return voice.category === activeVoiceCategory;
    });


    if (filtered.length === 0) {

        const message = document.createElement("p");

        message.textContent = "No voices in this category yet.";
        message.style.color = "var(--muted)";

        grid.appendChild(message);
        return;
    }


    filtered.forEach(voice => {

        const card = document.createElement("div");
        card.className = "voice-card";

        const avatar = document.createElement("div");
        avatar.className = "voice-avatar large";
        avatar.textContent = voice.name.charAt(0).toUpperCase();

        const title = document.createElement("h3");
        title.textContent = voice.name;

        const category = document.createElement("p");
        category.textContent = voice.category;

        const actions = document.createElement("div");
        actions.className = "voice-actions";

        const favoriteButton = document.createElement("button");
        favoriteButton.className = "secondary";
        favoriteButton.textContent =
            voice.favorite ? "★ Favorited" : "☆ Favorite";

        favoriteButton.addEventListener("click", async () => {
            await updateVoice(voice.id, {
                favorite: !Boolean(voice.favorite)
            });
        });

        const renameButton = document.createElement("button");
        renameButton.className = "secondary";
        renameButton.textContent = "Rename";

        renameButton.addEventListener("click", async () => {

            const newName = prompt("Voice name:", voice.name);

            if (newName === null) return;

            if (!newName.trim()) {
                alert("Voice name cannot be empty.");
                return;
            }

            await updateVoice(voice.id, {
                name: newName.trim()
            });
        });

        actions.append(favoriteButton, renameButton);

        card.append(avatar, title, category, actions);

        grid.appendChild(card);
    });
}


async function updateVoice(voiceId, changes) {

    const status = document.getElementById("voiceLibraryStatus");

    try {

        const response = await fetch(
            `/api/voices/${encodeURIComponent(voiceId)}`,
            {
                method: "PATCH",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify(changes)
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || "Update failed.");
        }

        await loadVoices();

        status.textContent = "Voice library updated.";

    } catch (error) {

        status.textContent = `Error: ${error.message}`;
    }
}


/* Category filters */

document.querySelectorAll(".library-tabs .tab")
    .forEach(button => {

        button.addEventListener("click", () => {

            document.querySelectorAll(".library-tabs .tab")
                .forEach(tab => tab.classList.remove("active"));

            button.classList.add("active");

            activeVoiceCategory = button.dataset.category;

            const communityBrowser =
                document.getElementById("communityBrowser");

            const voiceGrid =
                document.getElementById("voiceGrid");


            if (activeVoiceCategory === "community") {

                voiceGrid.hidden = true;
                communityBrowser.hidden = false;

                loadCommunityVoices();

            } else {

                voiceGrid.hidden = false;
                communityBrowser.hidden = true;

                renderVoiceLibrary();
            }
        });
    });


async function generateSpeech() {

    const text = script.value.trim();
    const voice = voiceSelect.value;

    if (!text) {
        generationStatus.textContent =
            "Please enter some text first.";
        return;
    }

    if (text.length > 3000) {
        generationStatus.textContent =
            "For now, please use fewer than 3,000 characters.";
        return;
    }

    if (!voice) {
        generationStatus.textContent =
            "Please select a voice.";
        return;
    }

    generateBtn.disabled = true;
    generateBtn.textContent = "Generating...";

    generationStatus.textContent =
        "Generating speech. Please wait...";

    audioResult.hidden = true;

    try {

        const response = await fetch("/api/generate", {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                text: text,
                voice: voice
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Generation failed"
            );
        }

        audioPlayer.src = data.audio_url;

        currentGeneratedAudioUrl =
            data.audio_url;

        audioFilename.value =
            data.display_name || "Recording";

        generatedVoiceName.textContent =
            data.voice_name || "Voice";

        updateDownloadFilename();

        audioResult.hidden = false;

        generationStatus.textContent =
            "Audio generated successfully!";

    } catch (error) {

        generationStatus.textContent =
            `Error: ${error.message}`;

    } finally {

        generateBtn.disabled = false;
        generateBtn.textContent = "Generate Audio";

    }
}

downloadAudio.addEventListener(
    "click",
    () => {

        if (!currentGeneratedAudioUrl) {
            return;
        }

        const cleanName =
            sanitizeFilename(
                audioFilename.value
            );

        const downloadUrl =
            `${currentGeneratedAudioUrl}` +
            `?download_name=` +
            encodeURIComponent(cleanName);

        const temporaryLink =
            document.createElement("a");

        temporaryLink.href =
            downloadUrl;

        temporaryLink.download =
            `${cleanName}.wav`;

        document.body.appendChild(
            temporaryLink
        );

        temporaryLink.click();

        temporaryLink.remove();
    }
);

function sanitizeFilename(name) {

    let clean = name
        .trim()

        // Remove characters that commonly cause
        // filename/path problems.
        .replace(/[<>:"/\\|?*\x00-\x1F]/g, "")

        // Collapse repeated spaces.
        .replace(/\s+/g, " ")

        // Prevent trailing dots/spaces.
        .replace(/[.\s]+$/g, "");

    if (!clean) {
        clean = "Recording";
    }

    return clean.slice(0, 150);
}

function updateDownloadFilename() {
    // The actual download filename is now
    // supplied when the Download button is clicked.
}

regenerateAudio.addEventListener(
    "click",
    () => {
        generateSpeech();
    }
);


generateBtn.addEventListener(
    "click",
    () => {
        if (longformMode.checked) {
            generateLongform();
        } else {
            generateSpeech();
        }
    }
);

longformMode.addEventListener(
    "change",
    () => {
        longformSection.classList.toggle(
            "is-active",
            longformMode.checked
        );

        if (!longformMode.checked) {
            longformProgress.hidden = true;
            longformError.hidden = true;
        }
    }
);

const longformRecovery =
    document.getElementById("longformRecovery");

const resumeLongformBtn =
    document.getElementById("resumeLongformBtn");

    function rememberLongformJob(jobId) {
    currentLongformJobId = jobId;

    localStorage.setItem(
        "pocketTTSLongformJob",
        jobId
    );
}


function forgetLongformJob() {
    currentLongformJobId = null;

    localStorage.removeItem(
        "pocketTTSLongformJob"
    );
}

loadVoices();

/* =========================================================
   Community Voice Browser
   ========================================================= */

let communityVoices = [];
let communityLoaded = false;
let currentPreview = null;
let currentPreviewButton = null;

async function loadCommunityVoices(force = false) {

    if (communityLoaded && !force) {
        renderCommunityVoices();
        return;
    }

    const grid =
        document.getElementById("communityVoiceGrid");

    const count =
        document.getElementById("communityCount");

    grid.innerHTML = "";
    count.textContent =
        "Loading Kyutai community voices...";

    try {

        const response =
            await fetch("/api/community-voices");

        if (!response.ok) {
            throw new Error(
                "Could not load community voices."
            );
        }

        const data = await response.json();

        communityVoices = data.voices || [];
        communityLoaded = true;

        renderCommunityVoices();

    } catch (error) {

        count.textContent =
            `Error: ${error.message}`;
    }
}


function renderCommunityVoices() {

    const grid =
        document.getElementById("communityVoiceGrid");

    const count =
        document.getElementById("communityCount");

    const search =
        document.getElementById("communitySearch")
            .value
            .trim()
            .toLowerCase();

    grid.innerHTML = "";

    const filtered = communityVoices.filter(voice => {

        const searchable =
            `${voice.name} ${voice.collection}`
                .toLowerCase();

        return searchable.includes(search);
    });


    count.textContent =
        `${filtered.length} voice samples found`;


    if (filtered.length === 0) {

        const empty =
            document.createElement("p");

        empty.className = "generation-status";

        empty.textContent =
            "No matching community voices found.";

        grid.appendChild(empty);

        return;
    }


    filtered.forEach(voice => {

        const card =
            document.createElement("div");

        card.className =
            "voice-card community-voice-card";


        const avatar =
            document.createElement("div");

        avatar.className =
            "voice-avatar large";

        avatar.textContent =
            voice.name
                .charAt(0)
                .toUpperCase();


        const title =
            document.createElement("h3");

        title.textContent =
            voice.name;


        const collection =
            document.createElement("p");

        collection.className =
            "voice-collection";

        collection.textContent =
            voice.collection;


        const actions =
            document.createElement("div");

        actions.className =
            "voice-actions";


        /* Preview button */

        const preview =
            document.createElement("button");

        preview.className =
            "secondary";

        preview.textContent =
            "▶ Preview";


        preview.addEventListener("click", async () => {

            /*
            * If this exact preview is already playing,
            * clicking again means STOP.
            */
            if (
                currentPreview &&
                currentPreviewButton === preview
            ) {
                currentPreview.pause();
                currentPreview.currentTime = 0;

                preview.textContent = "▶ Preview";

                currentPreview = null;
                currentPreviewButton = null;

                return;
            }


            /*
            * If another voice is playing,
            * stop it before starting this one.
            */
            if (currentPreview) {
                currentPreview.pause();
                currentPreview.currentTime = 0;

                if (currentPreviewButton) {
                    currentPreviewButton.textContent =
                        "▶ Preview";
                }

                currentPreview = null;
                currentPreviewButton = null;
            }


            /*
            * Start selected preview.
            */
            const audio = new Audio(voice.preview_url);

            currentPreview = audio;
            currentPreviewButton = preview;

            preview.textContent = "■ Stop";


            try {
                await audio.play();
            }

            catch (error) {
                console.error(error);

                preview.textContent = "▶ Preview";

                currentPreview = null;
                currentPreviewButton = null;

                alert(
                    "This voice preview could not be played."
                );

                return;
            }


            /*
            * Reset button when audio finishes naturally.
            */
            audio.addEventListener("ended", () => {

                if (currentPreview === audio) {
                    preview.textContent = "▶ Preview";

                    currentPreview = null;
                    currentPreviewButton = null;
                }
            });


            /*
            * Handle playback errors.
            */
            audio.addEventListener("error", () => {

                if (currentPreview === audio) {
                    preview.textContent = "▶ Preview";

                    currentPreview = null;
                    currentPreviewButton = null;
                }
            });
        });

        /* Add button — enabled next step */

        const add =
            document.createElement("button");

        add.className =
            "secondary community-add";

        add.textContent =
            "＋ Add to Library";

        add.addEventListener(
            "click",
            async () => {

                const originalText =
                    add.textContent;

                add.disabled = true;
                add.textContent =
                    "Downloading...";

                try {

                    const response = await fetch(
                        "/api/community-voices/install",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                name: voice.name,
                                path: voice.path
                            })
                        }
                    );


                    const data =
                        await response.json();


                    if (!response.ok) {
                        throw new Error(
                            data.detail ||
                            "Download failed."
                        );
                    }


                    add.textContent =
                        data.already_installed
                            ? "✓ Already Added"
                            : "✓ Added";


                    /*
                    * Reload our installed library.
                    * This also updates the narrator
                    * selector automatically.
                    */
                    await loadVoices();


                } catch (error) {

                    console.error(error);

                    add.textContent =
                        originalText;

                    alert(
                        `Could not add voice: ${
                            error.message
                        }`
                    );

                } finally {

                    /*
                    * Leave successful installs
                    * visually marked.
                    */
                    if (
                        !add.textContent
                            .startsWith("✓")
                    ) {
                        add.disabled = false;
                    }
                }
            }
        );


        actions.append(
            preview,
            add
        );


        card.append(
            avatar,
            title,
            collection,
            actions
        );


        grid.appendChild(card);
    });
}

function updateLongformProgress(job) {
    const total =
        Number(job.total_chunks) || 0;

    const completed =
        Number(job.completed_chunks) || 0;

    const percent =
        total > 0
            ? Math.round(
                (completed / total) * 100
            )
            : 0;

    longformProgress.hidden = false;

    longformPercent.textContent =
        `${percent}%`;

    longformProgressBar.style.width =
        `${percent}%`;

    longformChunkText.textContent =
        `${completed} / ${total} chunks`;

    if (
        job.status === "generating" &&
        job.current_chunk
    ) {
        longformStatusText.textContent =
            "Generating audio...";

        longformCurrentText.textContent =
            `Current chunk: ${job.current_chunk}`;
    } else if (job.status === "queued") {
        longformStatusText.textContent =
            "Queued...";

        longformCurrentText.textContent =
            "Preparing generation...";
    } else if (job.status === "completed") {
        longformStatusText.textContent =
            "Generation complete";

        longformCurrentText.textContent =
            "Preparing final audio...";
    } else if (job.status === "interrupted") {
        longformStatusText.textContent =
            "Generation interrupted";

        longformCurrentText.textContent =
            "Resume required";
    } else if (job.status === "failed") {
        longformStatusText.textContent =
            "Generation failed";

        longformCurrentText.textContent =
            "See error below";
    }
}

function stopLongformPolling() {
    if (longformPollingTimer) {
        clearTimeout(
            longformPollingTimer
        );

        longformPollingTimer = null;
    }
}

async function mergeLongformJob(jobId) {
    longformStatusText.textContent =
        "Merging audio...";

    longformCurrentText.textContent =
        "Combining generated chunks";

    const response = await fetch(
        `/api/longform/${jobId}/merge`,
        {
            method: "POST"
        }
    );

    const data = await response.json();

    if (!response.ok) {
        throw new Error(
            data.detail ||
            "Could not merge audio."
        );
    }

    return data;
}

function showLongformResult(data) {
    currentGeneratedAudioUrl =
        data.audio_url;

    audioPlayer.src =
        data.audio_url;

    audioFilename.value =
        data.display_name ||
        "Recording";

    generatedVoiceName.textContent =
        voice.options[
            voice.selectedIndex
        ]?.text || "Voice";

    audioResult.hidden = false;

    longformStatusText.textContent =
        "Ready";

    longformCurrentText.textContent =
        "Final recording created";

    longformPercent.textContent =
        "100%";

    longformProgressBar.style.width =
        "100%";
}

async function pollLongformJob(jobId) {
    try {
        const response = await fetch(
            `/api/longform/${jobId}/status`
        );

        const job = await response.json();

        if (!response.ok) {
            throw new Error(
                job.detail ||
                "Could not check generation status."
            );
        }

        updateLongformProgress(job);

        if (job.status === "completed") {
            stopLongformPolling();

            const merged =
                await mergeLongformJob(
                    jobId
                );

            showLongformResult(merged);
            longformRecovery.hidden = true;
            forgetLongformJob();

            generateBtn.disabled = false;

            return;
        }

        if (job.status === "interrupted") {
            stopLongformPolling();

            generateBtn.disabled = false;

            longformRecovery.hidden = false;

            longformError.hidden = false;

            longformError.textContent =
                "Generation was interrupted. " +
                "Your completed chunks were preserved.";

            return;
        }


        if (job.status === "failed") {
            stopLongformPolling();

            generateBtn.disabled = false;

            longformRecovery.hidden = false;

            longformError.hidden = false;

            longformError.textContent =
                job.error ||
                "Generation failed.";

            return;
        }

        longformPollingTimer =
            setTimeout(
                () =>
                    pollLongformJob(jobId),
                1000
            );

    } catch (error) {
        stopLongformPolling();

        generateBtn.disabled = false;

        longformError.hidden = false;
        longformError.textContent =
            error.message;
    }
}

async function generateLongform() {
    const text = script.value.trim();

    if (!text) {
        generationStatus.textContent =
            "Please enter some text.";

        return;
    }

    stopLongformPolling();

    longformError.hidden = true;
    longformError.textContent = "";

    longformProgress.hidden = false;

    longformProgressBar.style.width =
        "0%";

    longformPercent.textContent =
        "0%";

    longformChunkText.textContent =
        "0 / 0 chunks";

    longformStatusText.textContent =
        "Starting...";

    longformCurrentText.textContent =
        "Preparing script";

    audioResult.hidden = true;

    generateBtn.disabled = true;

    longformRecovery.hidden = true;

    generationStatus.textContent =
        "Long-form generation started.";

    try {
        const response = await fetch(
            "/api/longform/start",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    text: text,
                    voice: voice.value
                })
            }
        );

        const job = await response.json();

        if (!response.ok) {
            throw new Error(
                job.detail ||
                "Could not start generation."
            );
        }

        rememberLongformJob(
            job.job_id
        );

        updateLongformProgress(job);

        pollLongformJob(
            currentLongformJobId
        );

    } catch (error) {
        generateBtn.disabled = false;

        longformError.hidden = false;
        longformError.textContent =
            error.message;

        generationStatus.textContent =
            "Generation failed.";
    }
}

async function resumeLongformGeneration() {
    if (!currentLongformJobId) {
        return;
    }

    resumeLongformBtn.disabled = true;

    longformError.hidden = true;

    longformStatusText.textContent =
        "Resuming...";

    try {
        const response = await fetch(
            `/api/longform/` +
            `${currentLongformJobId}/resume`,
            {
                method: "POST"
            }
        );

        const job = await response.json();

        if (!response.ok) {
            throw new Error(
                job.detail ||
                "Could not resume generation."
            );
        }

        longformRecovery.hidden = true;

        generateBtn.disabled = true;

        updateLongformProgress(job);

        pollLongformJob(
            currentLongformJobId
        );

    } catch (error) {
        longformError.hidden = false;

        longformError.textContent =
            error.message;

    } finally {
        resumeLongformBtn.disabled = false;
    }
}

resumeLongformBtn.addEventListener(
    "click",
    resumeLongformGeneration
);

async function recoverLongformJob() {
    const savedJobId =
        localStorage.getItem(
            "pocketTTSLongformJob"
        );

    if (!savedJobId) {
        return;
    }

    try {
        const response = await fetch(
            `/api/longform/` +
            `${savedJobId}/status`
        );

        if (!response.ok) {
            forgetLongformJob();
            return;
        }

        const job = await response.json();

        currentLongformJobId =
            savedJobId;

        longformMode.checked = true;

        longformSection.classList.add(
            "is-active"
        );

        updateLongformProgress(job);

        if (
            job.status === "interrupted" ||
            job.status === "failed"
        ) {
            longformRecovery.hidden = false;

            longformError.hidden = false;

            longformError.textContent =
                job.status === "interrupted"
                    ? "Generation was interrupted. " +
                      "Your completed chunks were preserved."
                    : job.error ||
                      "Generation failed.";

            return;
        }

        if (
            job.status === "queued" ||
            job.status === "generating"
        ) {
            generateBtn.disabled = true;

            pollLongformJob(
                savedJobId
            );

            return;
        }

        if (job.status === "completed") {
            /*
             * Generation finished while the
             * browser was unavailable.
             *
             * Merge it and restore the result.
             */
            const merged =
                await mergeLongformJob(
                    savedJobId
                );

            showLongformResult(merged);

            longformRecovery.hidden = true;

            forgetLongformJob();
        }

    } catch (error) {
        console.error(
            "Long-form recovery failed:",
            error
        );
    }
}

recoverLongformJob();


/* Search */

document
    .getElementById("communitySearch")
    .addEventListener(
        "input",
        renderCommunityVoices
    );


/* Refresh */

document
    .getElementById("refreshCommunityBtn")
    .addEventListener(
        "click",
        () => loadCommunityVoices(true)
    );