/**
 * Shared command execution utility
 *
 * Provides a safe way to execute shell commands without triggering
 * interactive shell features like .bashrc sourcing.
 */

import { spawn } from "child_process";

export interface ExecOptions {
  timeout?: number;
  cwd?: string;
}

export interface ExecResult {
  stdout: string;
  stderr: string;
}

export interface ExecError extends Error {
  code?: number;
  stdout?: string;
  stderr?: string;
}

/**
 * Execute a command using spawn with bash --norc --noprofile to avoid sourcing
 * .bashrc.d scripts (which can trigger Bitwarden password prompts).
 *
 * This replaces exec() which spawns an interactive shell by default.
 */
export async function execAsync(
  command: string,
  options?: ExecOptions
): Promise<ExecResult> {
  return new Promise((resolve, reject) => {
    // Use bash with --norc --noprofile to prevent sourcing any startup files
    // -c tells bash to execute the following command string
    const proc = spawn("/bin/bash", ["--norc", "--noprofile", "-c", command], {
      cwd: options?.cwd,
      env: {
        ...process.env,
        // Extra safety: clear env vars that could trigger rc file sourcing
        BASH_ENV: "",
        ENV: "",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let killed = false;

    // Handle timeout
    const timeout = options?.timeout || 30000;
    const timer = setTimeout(() => {
      killed = true;
      proc.kill("SIGTERM");
      reject(new Error(`Command timed out after ${timeout}ms`));
    }, timeout);

    proc.stdout.on("data", (data) => {
      stdout += data.toString();
    });
    proc.stderr.on("data", (data) => {
      stderr += data.toString();
    });

    proc.on("close", (code) => {
      clearTimeout(timer);
      if (killed) return;

      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        const error: ExecError = new Error(
          `Command failed with exit code ${code}: ${stderr}`
        );
        error.code = code ?? undefined;
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
      }
    });

    proc.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}
