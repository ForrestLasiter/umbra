package com.forrestlasiter.umbra.system

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The sentences the user reads. Each test is a promise about wording: a result
 * must never sound better than it was.
 */
class PostureReportTest {

    @Test fun a_clean_apply_counts_only_what_was_enforced() {
        val outcomes = listOf(
            Outcome("firewall", Change.ENFORCED, ok = true),
            Outcome("mac", Change.KEPT, ok = true),
            Outcome("bluetooth_off", Change.UNTOUCHED, ok = true),
        )
        assertEquals("home: 2 system control(s) enforced.", PostureReport.summarize("home", outcomes))
    }

    @Test fun a_failure_is_named_and_is_never_called_enforced() {
        val outcomes = listOf(
            Outcome("firewall", Change.ENFORCED, ok = true),
            Outcome("wireguard", Change.ENFORCED, ok = false),
        )
        val text = PostureReport.summarize("travel", outcomes)
        assertTrue(text.contains("could not change wireguard"))
        assertFalse(text.contains("enforced."))
    }

    @Test fun something_unavailable_carries_its_reason() {
        val outcomes = listOf(
            Outcome("firewall", Change.ENFORCED, ok = true),
            Outcome("wireguard", Change.UNAVAILABLE, ok = true, note = "no WireGuard config imported yet"),
        )
        assertEquals(
            "travel: 1 system control(s) enforced. Not enforced: wireguard (no WireGuard config imported yet).",
            PostureReport.summarize("travel", outcomes),
        )
    }

    @Test fun leaving_a_posture_says_so_plainly() {
        val outcomes = listOf(Outcome("firewall", Change.RESTORED, ok = true))
        assertEquals("Back to normal: system settings restored.", PostureReport.summarize("normal", outcomes))
    }

    @Test fun a_failed_restore_is_not_reported_as_back_to_normal() {
        val outcomes = listOf(Outcome("firewall", Change.RESTORED, ok = false))
        assertTrue(PostureReport.summarize("normal", outcomes).contains("could not change firewall"))
    }

    @Test fun audit_counts_only_measured_true_as_verified() {
        val items = listOf(
            AuditItem("firewall", holding = true),
            AuditItem("mac", holding = true),
            AuditItem("bluetooth_off", holding = false),
            AuditItem("wireguard", holding = null, note = "no config"),
        )
        assertEquals(
            "travel: 2 of 4 system controls verified. DRIFTED: bluetooth_off. Not enforced: wireguard.",
            PostureReport.summarizeAudit("travel", items),
        )
    }

    @Test fun a_fully_held_posture_audits_clean() {
        val items = listOf(AuditItem("firewall", true), AuditItem("mac", true))
        assertEquals("home: 2 of 2 system controls verified.", PostureReport.summarizeAudit("home", items))
    }

    @Test fun normal_has_nothing_to_audit() {
        assertEquals("normal: no posture is active.", PostureReport.summarizeAudit("normal", emptyList()))
    }
}
