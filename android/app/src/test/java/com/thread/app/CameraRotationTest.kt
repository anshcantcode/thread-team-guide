package com.thread.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CameraRotationTest {
    @Test fun displayRotationChangesCaptureOrientationInPlace() {
        val rotation = CameraRotation(0)

        assertEquals(90, rotation.captureDegrees(90))
        for ((displayDegrees, expectedCaptureDegrees) in listOf(90 to 0, 180 to 270, 270 to 180, 0 to 90)) {
            assertTrue(rotation.update(displayDegrees))
            assertEquals(expectedCaptureDegrees, rotation.captureDegrees(90))
            assertFalse(rotation.update(displayDegrees))
        }
    }
}
