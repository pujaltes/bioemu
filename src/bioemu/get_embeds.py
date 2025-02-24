# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

StrPath = str | os.PathLike


def shahexencode(s: str) -> str:
    """Simple sha256 string encoding"""
    return hashlib.sha256(s.encode()).hexdigest()


def write_fasta(seqs: list[str], fasta_file: StrPath, ids: list[str] | None = None) -> None:
    """Writes sequences in `seqs` in FASTA format

    Args:
        seqs (list[str]): Sequences in 1-letter amino-acid code
        fasta_file (StrPath): Destination FASTA file
    """
    Path(fasta_file).parent.mkdir(parents=True, exist_ok=True)
    if ids is None:
        ids = list(range(len(seqs)))  # type: ignore

    seq_records = [SeqRecord(seq=Seq(seq), id=str(_id)) for _id, seq in zip(ids, seqs)]
    with open(fasta_file, "w") as fasta_handle:
        SeqIO.write(seq_records, fasta_handle, format="fasta")


def _get_colabfold_install_dir() -> StrPath:
    """Returns the directory where colabfold is installed"""
    return os.getenv("COLABFOLD_DIR", os.path.join(os.path.expanduser("~"), ".localcolabfold"))


def _get_default_embeds_dir() -> StrPath:
    """Returns the directory where precomputed embeddings are stored"""
    return os.path.join(_get_colabfold_install_dir(), "embeds_cache")


def run_colabfold(
    fasta_file: StrPath,
    res_dir: StrPath,
    colabfold_env: dict[str, str],
    msa_host_url: str | None = None,
) -> int:
    cmd = [
        "colabfold_batch",
        fasta_file,
        res_dir,
        "--num-models",
        "1",
        "--model-order",
        "3",
        "--model-type",
        "alphafold2",
        "--num-recycle",
        "0",
        "--save-single-representations",
        "--save-pair-representations",
    ]
    if msa_host_url is not None:
        cmd.extend(["--host-url", msa_host_url])
    return subprocess.call(cmd, env=colabfold_env)


def get_colabfold_embeds(
    seq: str, cache_embeds_dir: StrPath | None, msa_host_url: str | None = None
) -> tuple[StrPath, StrPath]:
    """
    Uses colabfold to retrieve embeddings for a given sequence. If the embeddings are already stored under `cache_embeds_dir`,
    the cached embeddings are returned. Otherwise, colabfold is used to compute the embeddings and they are saved under `cache_embeds_dir`.

    Args:
        seq: Protein sequence to query
        cache_embeds_dir: Cache directory where embeddings will be stored. If None, defaults to a child of the colabfold install directory.

    Returns:
        Path to resulting single and pair embeddings
    """
    seqsha = shahexencode(seq)

    # Setup embedding cache
    cache_embeds_dir = cache_embeds_dir or _get_default_embeds_dir()
    os.makedirs(cache_embeds_dir, exist_ok=True)

    # Check whether embeds have already been computed
    single_rep_file = os.path.join(cache_embeds_dir, f"{seqsha}_single.npy")
    pair_rep_file = os.path.join(cache_embeds_dir, f"{seqsha}_pair.npy")

    if os.path.exists(single_rep_file) and os.path.exists(pair_rep_file):
        return single_rep_file, pair_rep_file

    # If we don't already have embeds, run colabfold
    colabfold_dir = _get_colabfold_install_dir()
    assert os.path.exists(
        colabfold_dir
    ), f"Colabfold installation not found under {colabfold_dir}. Did you run setup.sh?"

    colabfold_env = os.environ.copy()
    colabfold_env["PATH"] += ":" + os.path.join(
        colabfold_dir, "localcolabfold", "colabfold-conda", "bin"
    )
    # Delete MPLBACKEND to avoid matplotlib issues when running in jupyter notebook
    colabfold_env.pop("MPLBACKEND", None)

    with tempfile.TemporaryDirectory() as tempdir:
        fasta_file = os.path.join(tempdir, f"{seqsha}.fasta")
        res_dir = os.path.join(tempdir, "results")
        os.makedirs(res_dir)
        write_fasta(seqs=[seq], fasta_file=fasta_file, ids=[seqsha])
        res = run_colabfold(fasta_file, res_dir, colabfold_env, msa_host_url)
        assert res == 0, "Failed to run colabfold_batch"

        single_rep_tempfile = os.path.join(
            res_dir,
            f"{seqsha}__unknown_description__single_repr_evo_rank_001_alphafold2_model_3_seed_000.npy",
        )
        pair_rep_tempfile = os.path.join(
            res_dir,
            f"{seqsha}__unknown_description__pair_repr_evo_rank_001_alphafold2_model_3_seed_000.npy",
        )
        shutil.copy(single_rep_tempfile, single_rep_file)
        shutil.copy(pair_rep_tempfile, pair_rep_file)
        # Just to be friendly, we also keep a .fasta as a human-readable record of what sequence this is for.
        shutil.copy(fasta_file, os.path.join(cache_embeds_dir, f"{seqsha}.fasta"))

    return single_rep_file, pair_rep_file
