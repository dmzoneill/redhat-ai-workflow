/**
 * Test Chat Refresh - Experimental module to test refreshing Cursor's chat list
 *
 * This is a temporary test file to investigate how to trigger Cursor to reload
 * its chat list from the database without a full window reload.
 */

import * as vscode from "vscode";

// TEST chat ID to delete
const TEST_CHAT_ID = "3a303e84-2910-4ffb-81a2-6d3b94848e3a";

/**
 * Test deleting a chat using Cursor's composer.deleteChat command
 */
export async function testDeleteChat(): Promise<void> {
    const results: string[] = [];
    results.push(`Testing delete for chat ID: ${TEST_CHAT_ID}`);
    results.push("");

    // First, list ALL commands containing delete, remove, archive, close, clear
    results.push("=== Commands with delete/remove/archive/close/clear ===");
    try {
        const allCommands = await vscode.commands.getCommands(true);
        const relevantCommands = allCommands.filter(cmd => {
            const lower = cmd.toLowerCase();
            return lower.includes("delete") ||
                   lower.includes("remove") ||
                   lower.includes("archive") ||
                   lower.includes("close") ||
                   lower.includes("clear");
        }).sort();

        results.push(`Found ${relevantCommands.length} relevant commands:`);
        for (const cmd of relevantCommands) {
            results.push(`  - ${cmd}`);
        }
    } catch (e: any) {
        results.push(`  ✗ Failed to list commands: ${e.message || e}`);
    }

    results.push("");
    results.push("=== Testing Potential Delete Commands ===");

    // Test 1: workbench.action.backgroundComposer.archive
    results.push("");
    results.push("Test 1: workbench.action.backgroundComposer.archive (with chat ID)");
    try {
        await vscode.commands.executeCommand("workbench.action.backgroundComposer.archive", TEST_CHAT_ID);
        results.push("  ✓ Command executed");
    } catch (e: any) {
        results.push(`  ✗ Failed: ${e.message || e}`);
    }

    // Test 2: composer.clearComposerTabs
    results.push("");
    results.push("Test 2: composer.clearComposerTabs");
    try {
        await vscode.commands.executeCommand("composer.clearComposerTabs");
        results.push("  ✓ Command executed");
    } catch (e: any) {
        results.push(`  ✗ Failed: ${e.message || e}`);
    }

    // Test 3: composer.closeComposerTab with chat ID
    results.push("");
    results.push("Test 3: composer.closeComposerTab (with chat ID)");
    try {
        await vscode.commands.executeCommand("composer.closeComposerTab", TEST_CHAT_ID);
        results.push("  ✓ Command executed");
    } catch (e: any) {
        results.push(`  ✗ Failed: ${e.message || e}`);
    }

    // Test 4: Open the history panel - maybe it has delete UI
    results.push("");
    results.push("Test 4: composer.showComposerHistory (opens history panel)");
    try {
        await vscode.commands.executeCommand("composer.showComposerHistory");
        results.push("  ✓ Command executed - check if history panel has delete option");
    } catch (e: any) {
        results.push(`  ✗ Failed: ${e.message || e}`);
    }

    // Show results
    const doc = await vscode.workspace.openTextDocument({
        content: results.join("\n"),
        language: "markdown"
    });
    await vscode.window.showTextDocument(doc);
}

/**
 * Try various approaches to refresh Cursor's chat list
 */
export async function testChatRefresh(): Promise<void> {
    const results: string[] = [];

    // Approach 1: Try opening the history panel
    try {
        await vscode.commands.executeCommand("composer.showComposerHistory");
        results.push("✓ composer.showComposerHistory executed");
    } catch (e) {
        results.push(`✗ composer.showComposerHistory failed: ${e}`);
    }

    // Wait a moment
    await new Promise(resolve => setTimeout(resolve, 500));

    // Approach 2: Try focusing the composer
    try {
        await vscode.commands.executeCommand("composer.focusComposer");
        results.push("✓ composer.focusComposer executed");
    } catch (e) {
        results.push(`✗ composer.focusComposer failed: ${e}`);
    }

    // Approach 3: List all available commands containing "composer" or "chat"
    try {
        const allCommands = await vscode.commands.getCommands(true);
        const relevantCommands = allCommands.filter(cmd =>
            cmd.toLowerCase().includes("composer") ||
            cmd.toLowerCase().includes("chat") ||
            cmd.toLowerCase().includes("history")
        ).sort();

        results.push(`\nFound ${relevantCommands.length} relevant commands:`);
        for (const cmd of relevantCommands.slice(0, 30)) {
            results.push(`  - ${cmd}`);
        }
        if (relevantCommands.length > 30) {
            results.push(`  ... and ${relevantCommands.length - 30} more`);
        }
    } catch (e) {
        results.push(`✗ Failed to list commands: ${e}`);
    }

    // Show results
    const doc = await vscode.workspace.openTextDocument({
        content: results.join("\n"),
        language: "markdown"
    });
    await vscode.window.showTextDocument(doc);
}

/**
 * Register the test commands (internal only, not in command palette)
 */
export function registerTestCommand(_context: vscode.ExtensionContext): void {
    // Test commands removed from command palette
    // Can be re-added when needed for debugging
}
