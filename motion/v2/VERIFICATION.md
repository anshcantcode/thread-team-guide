# Version 2 verification

Production completed 15 September 2026. The film's weather, clock and example
flight dates remain tied to the documented 14 September capture.

## Media checks

Both deliverables are 43 seconds at 60 fps, with 2,580 frames each. Landscape is
2560 × 1440; portrait is 1080 × 1920. H.264, YUV 4:2:0, BT.709 colour,
48 kHz stereo AAC, optional English captions and MP4 fast-start are included.

`finish_v2.py` checks dimensions, duration, frame count and audio format, then
decodes every frame in both completed files. Final measured loudness, true peak,
byte sizes and SHA-256 hashes are recorded in `output/manifest.json`. The final
mix is approximately -16.2 LUFS with a true peak of -1.2 dBTP.

## Visual inspection and revisions

Keyframes were composed and checked in both aspect ratios. Contact sheets were
then extracted from the encoded videos at 28 positions, including closely spaced
frames around the flight update and the flight-to-weather transition. Full-size
weather and sports frames were also inspected separately.

The following visible issues were corrected during production:

- Flight destination, city, arrival and price initially overprinted during the
  update. These now roll through clipped text slots, with a 600 ms update.
- The weather icon crowded the temperature. It now has its own position, with
  a stronger image gradient under the text and more forecast spacing.
- Full-scene dissolves briefly double-exposed result text. Complementary 320 ms
  moving masks now keep the two compositions separate during each transition.
- The widget wallpaper initially extended beyond the phone. It is now contained,
  and the frame grows with the contracting widget.
- The sports plot initially cleared and redrew at the format switch. Its points
  now morph, with opponent labels and a stable graph area.
- The fifth sports point's reveal calculation left its label at 10% opacity.
  This was corrected; the 75-run point and its GT label finish at full opacity.
- Closing words initially crossfaded on top of each other. They now appear in
  discrete rhythmic beats, followed by a longer logo hold through 43 seconds.

The final sports labels read 105, 58, 15, 43 and 75, matching the captured
five-innings T20 dataset. The airport change finishes as MAA → BOM, and the
film shows the separate sample-fare note throughout the flight shot.

## Audio inspection

The twelve user requests were generated in one performance. Model-assisted
audio transcription found all twelve present, without missing words, spoken
directions or accidental truncation, and reported consistent vocal identity.
The final spoken signature is preserved with room for its tail.

Feedback about masking led to stronger speech ducking, quieter effects during
speech and a further 1.5 dB music reduction in the request sequence. The
assistant's deliberate cutoff now has an 80 ms release overlapping the start
of the user's correction; the separate tape-stop chirp was removed. The final
caption reflects the interrupted utterance: "Here are the best—".

Audio critique was **model-assisted**, alongside signal analysis; no claim of
direct human listening is made. The raw listening notes are retained in the local production archive.
Early video critiques are retained in the local output archive. Some model
claims, such as a nonexistent bar chart or a final black fade, did not match
the actual frames. Concrete visual findings were checked against rendered
media before changes were made. These reports are editorial inputs, not an
independent score, hackathon endorsement or product capability certification.

The final landscape and portrait media reviews reported no verified visual
issues and no audible issues. Both explicitly noted that sparse video sampling
cannot establish the quality of every easing curve. The encoded transition
samples and full-size frames were inspected separately for that reason.

## Scope

This revision changes the product film and its production tools. It does not
modify the Android app or turn the demonstration flight provider into a live
airline integration. See ASSETS.md and SCRIPT.md for data and presentation scope.
