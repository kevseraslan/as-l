import sys

filepath = r"c:\Users\kevse\OneDrive\Desktop\girisim\ReviseMeSon\templates\timer.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

start_tag = "<script>"
end_tag = "</script>"
start_idx = content.rfind(start_tag)

if start_idx != -1:
    content = content[:start_idx] + '''<script>
    document.addEventListener("DOMContentLoaded", function() {
        let timerDisplay = document.getElementById("timerDisplay");
        let startBtn = document.getElementById("startBtn");
        let stopBtn = document.getElementById("stopBtn");
        let resetBtn = document.getElementById("resetBtn");
        let progressCircle = document.getElementById("progressCircle");
        let workDurationInput = document.getElementById("workDuration");
        let saveSettingsBtn = document.getElementById("saveSettingsBtnMain");
        
        // Settings Sync functionality
        if(saveSettingsBtn) {
            saveSettingsBtn.addEventListener('click', function() {
                let mins = parseInt(workDurationInput.value);
                if(isNaN(mins) || mins <= 0) mins = 25;
                if(window.PomodoroManager) window.PomodoroManager.reset(mins * 60);
            });
        }

        if(startBtn) {
            startBtn.addEventListener("click", () => {
                if(!window.PomodoroManager) return;
                let state = window.PomodoroManager.getState();
                if (state.totalTime <= 0 || isNaN(state.totalTime)) {
                     let mins = parseInt(workDurationInput.value);
                     window.PomodoroManager.start((isNaN(mins) ? 25 : mins) * 60);
                } else {
                     window.PomodoroManager.start();
                }
            });
        }
        
        if(stopBtn) stopBtn.addEventListener("click", () => {
            if(window.PomodoroManager) window.PomodoroManager.pause()
        });
        
        if(resetBtn) {
            resetBtn.addEventListener("click", () => {
                let mins = parseInt(workDurationInput.value);
                if(isNaN(mins) || mins<=0) mins = 25;
                if(window.PomodoroManager) window.PomodoroManager.reset(mins * 60);
            });
        }
        
        // This receives ticks from the global manager in header_modern.html
        window.onPomodoroTick = function(remaining, totalTime, isRunning) {
            if(!timerDisplay) return;
            
            // Update big display
            let minutes = Math.floor(remaining / 60);
            let seconds = remaining % 60;
            timerDisplay.textContent = ${minutes.toString().padStart(2, '0')}:;
            
            // Update circle stably
            if(progressCircle) {
                let circumference = 1068; // Based on original file fallback and standard SVG circle sizes
                progressCircle.style.strokeDasharray = ${circumference} ;
            
                let safeTotal = (totalTime > 0 && !isNaN(totalTime)) ? totalTime : 1500;
                let offset = circumference - (remaining / safeTotal) * circumference;
                progressCircle.style.strokeDashoffset = offset;
            }
            
            // Update buttons
            if (isRunning) {
                if(startBtn) startBtn.classList.add("hidden");
                if(stopBtn) stopBtn.classList.remove("hidden");
            } else {
                if(startBtn) startBtn.classList.remove("hidden");
                if(stopBtn) stopBtn.classList.add("hidden");
            }
        };
        
        // Give immediate first tick update directly relying on current state
        if(window.PomodoroManager) {
            window.PomodoroManager.tick();
        } else {
            console.error("PomodoroManager not found! Make sure header_modern.html defines it globally without DOMContentLoaded wrappers wrapping the object.");
        }
    });
</script>'''

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated timer.html successfully with safe logic.")
