<script lang="ts">
	import { enhance } from '$app/forms';
	import type { ActionData } from './$types';

	export let form: ActionData;

	let uploading = false;
</script>

<div class="container mx-auto max-w-2xl p-4">
	<h1 class="mb-6 text-3xl font-bold">Ingest Data</h1>

	<div class="card bg-base-100 shadow-xl">
		<div class="card-body">
			<h2 class="card-title">Upload Export</h2>
			<p class="text-base-content/70">
				Upload a .zip export from Claude or ChatGPT. The system will attempt to detect the format automatically.
			</p>

			<form
				method="POST"
				enctype="multipart/form-data"
				use:enhance={() => {
					uploading = true;
					return async ({ update }) => {
						uploading = false;
						await update();
					};
				}}
				class="mt-4 flex flex-col gap-4"
			>
				<div class="form-control w-full">
					<label class="label" for="source">
						<span class="label-text">Source System</span>
					</label>
					<select name="source" class="select select-bordered" id="source">
						<option value="auto">Auto Detect</option>
						<option value="claude">Claude</option>
						<option value="chatgpt">ChatGPT</option>
					</select>
				</div>

				<div class="form-control w-full">
					<label class="label" for="file">
						<span class="label-text">Export ZIP File</span>
					</label>
					<input
						type="file"
						name="file"
						id="file"
						accept=".zip"
						required
						class="file-input file-input-bordered w-full"
					/>
				</div>

				<div class="card-actions mt-4 justify-end">
					<button class="btn btn-primary" type="submit" disabled={uploading}>
						{#if uploading}
							<span class="loading loading-spinner"></span>
							Uploading...
						{:else}
							Start Ingestion
						{/if}
					</button>
				</div>
			</form>

			{#if form?.success}
				<div class="alert alert-success mt-4">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-6 w-6 shrink-0 stroke-current"
						fill="none"
						viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
						/></svg
					>
					<span>{form.message}</span>
				</div>
			{/if}

			{#if form?.error}
				<div class="alert alert-error mt-4">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-6 w-6 shrink-0 stroke-current"
						fill="none"
						viewBox="0 0 24 24"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
						/></svg
					>
					<span>{form.error}</span>
				</div>
			{/if}
		</div>
	</div>
</div>
