import { CronJob } from 'cron'

export class Scheduler {
  private jobs: Map<string, CronJob> = new Map()

  schedule(id: string, cronExpression: string, task: () => Promise<void>): void {
    // Cancel existing job if it exists
    this.cancel(id)

    const job = new CronJob(
      cronExpression,
      async () => {
        try {
          await task()
        } catch (error) {
          console.error(`Scheduled task ${id} failed:`, error)
        }
      },
      null,
      true, // Start immediately
      'UTC'
    )

    this.jobs.set(id, job)
    console.log(`Scheduled task ${id} with expression: ${cronExpression}`)
  }

  cancel(id: string): void {
    const job = this.jobs.get(id)
    if (job) {
      job.stop()
      this.jobs.delete(id)
      console.log(`Cancelled scheduled task: ${id}`)
    }
  }

  cancelAll(): void {
    for (const [id, job] of this.jobs) {
      job.stop()
    }
    this.jobs.clear()
    console.log('Cancelled all scheduled tasks')
  }

  listJobs(): string[] {
    return Array.from(this.jobs.keys())
  }

  isScheduled(id: string): boolean {
    return this.jobs.has(id)
  }
}
