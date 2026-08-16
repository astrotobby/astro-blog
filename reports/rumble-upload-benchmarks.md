# Rumble upload benchmarks

Official Rumble support states that visibility is selected during upload and can later be changed from the account Content tab. The public option is distinct from unlisted and private. Source: https://rumble.support/help/set-video-visibility-public-unlisted-mode

Rumble’s current help hub, updated 27 Oct 2025, links separate guidance for the three-step upload flow, waiting for an encoding server to claim a video, auto-syndication, and visibility settings. This indicates that a successful form submission is not identical to the video being fully encoded or immediately discoverable. The uploader should therefore record the resulting content URL or account-content state and poll for a terminal status rather than returning success immediately after clicking the final submit button. Source: https://rumble.support/help/upload-process
