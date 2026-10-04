package com.thread.app

import org.junit.Assert.*
import org.junit.Test

class BubbleLogicTest {
    private val safe = BubbleBounds(24, 110, 1056, 2220)
    @Test fun dragCannotCoverStatusNavigationOrGestureInsets() {
        assertEquals(BubblePoint(24, 110), safe.clamp(-400, -100, 192))
        assertEquals(BubblePoint(864, 2028), safe.clamp(4000, 4000, 192))
    }
    @Test fun snapsNearestPhysicalEdgeWithoutChangingSafeVerticalPosition() {
        assertEquals(BubblePoint(24, 800), safe.snap(100, 800, 192))
        assertEquals(BubblePoint(864, 800), safe.snap(760, 800, 192))
        assertEquals(24, safe.snap(444, 800, 192).x) // Tie is deterministic.
    }
    @Test fun resizedDisplayClampsOldPortraitPosition() {
        assertEquals(BubblePoint(408, 400), BubbleBounds(16, 80, 600, 592).snap(900, 2000, 192))
        assertEquals(BubblePoint(8, 8), BubbleBounds(8, 8, 48, 48).snap(500, 500, 64))
    }
    @Test fun bottomTargetRequiresActualProximityNotMerelyDraggingLow() {
        val target = safe.dismissTarget(192)
        assertEquals(BubblePoint(444, 2028), target)
        assertTrue(onDismissTarget(target, target, 192))
        assertFalse(onDismissTarget(BubblePoint(24, 2028), target, 192))
        assertFalse(onDismissTarget(target.copy(y = 1500), target, 192))
    }
    @Test fun requiresExplicitOptInOverlayAndVisibleNotification() {
        for (optIn in listOf(false, true)) for (overlay in listOf(false, true)) for (notifications in listOf(false, true)) {
            assertEquals(optIn && overlay && notifications, BubblePermissionGate.canShow(optIn, overlay, notifications))
        }
    }
    @Test fun overlayPermissionCannotSubstituteForConsentOrMicrophoneForegroundEligibility() {
        assertEquals(BubbleTap.OPEN_THREAD, BubblePermissionGate.tap(false, true, true, true, false))
        assertEquals(BubbleTap.OPEN_THREAD, BubblePermissionGate.tap(true, false, true, true, false))
        assertEquals(BubbleTap.OPEN_THREAD, BubblePermissionGate.tap(true, true, false, false, false))
        assertEquals(BubbleTap.OPEN_THREAD, BubblePermissionGate.tap(true, true, false, true, false)) // Text-only connection.
        assertEquals(BubbleTap.TALK_IN_SESSION, BubblePermissionGate.tap(true, true, true, true, false))
        assertEquals(BubbleTap.NONE, BubblePermissionGate.tap(true, true, true, false, true))
    }
    @Test fun hapticsOnlyForTransitionsAndFreshReceiptsAndNeverReplayWhenReenabled() {
        val feedback = BubbleFeedback("saved", false)
        assertEquals(BubbleFeedback.Change(false, false), feedback.update(false, "saved", true))
        assertEquals(BubbleFeedback.Change(true, false), feedback.update(true, "saved", true))
        assertEquals(BubbleFeedback.Change(false, false), feedback.update(true, "saved", true))
        assertEquals(BubbleFeedback.Change(false, true), feedback.update(false, "new", true))
        assertEquals(BubbleFeedback.Change(false, false), feedback.update(true, "disabled-receipt", false))
        assertEquals(BubbleFeedback.Change(false, false), feedback.update(true, "disabled-receipt", true))
    }
}
