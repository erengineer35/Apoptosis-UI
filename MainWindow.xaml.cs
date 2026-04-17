using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Win32;

// Resolve ambiguous references with System.Windows.Forms
using Application = System.Windows.Application;
using Brushes = System.Windows.Media.Brushes;
using Cursors = System.Windows.Input.Cursors;
using MessageBox = System.Windows.MessageBox;
using MouseEventArgs = System.Windows.Input.MouseEventArgs;
using SaveFileDialog = Microsoft.Win32.SaveFileDialog;

// Shape types (use full namespace to avoid Path conflict with System.IO.Path)
using Line = System.Windows.Shapes.Line;
using Rectangle = System.Windows.Shapes.Rectangle;
using Ellipse = System.Windows.Shapes.Ellipse;

namespace ApoptosisUI;

public partial class MainWindow : Window
{
    private readonly string _pythonExecutable;
    private readonly string _scriptPath;
    private readonly ObservableCollection<MetricViewModel> _metrics = new();
    private readonly List<ProcessedImageRecord> _processedHistory = new();
    private readonly HistoryManager _historyManager = new();
    private bool _sampleReady;
    private bool _isBusy;
    private string? _uploadedSamplePath;
    private int _totalProcessed;
    private AnalysisResults? _lastResults;

    // User session info
    private readonly string? _currentUsername;
    private readonly bool _isGuest;

    // Data classes for JSON parsing
    private sealed class AnalysisResults
    {
        public string? Status { get; set; }
        public string? Timestamp { get; set; }
        public string? InputFile { get; set; }
        public List<string>? ActionsCompleted { get; set; }
        public Statistics? Statistics { get; set; }
        public List<string>? OutputFiles { get; set; }
        public string? PdfReport { get; set; }
    }

    private sealed class Statistics
    {
        [System.Text.Json.Serialization.JsonPropertyName("class_distribution")]
        public ClassDistribution? ClassDistribution { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("cell_count")]
        public int CellCount { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("total_cells")]
        public int TotalCells { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("mean_cell_area")]
        public double MeanCellArea { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("cell_counts_by_class")]
        public CellCountsByClass? CellCountsByClass { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("area_stats")]
        public AreaStats? AreaStats { get; set; }
    }

    private sealed class CellCountsByClass
    {
        [System.Text.Json.Serialization.JsonPropertyName("healthy")]
        public int Healthy { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("affected")]
        public int Affected { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("irrelevant")]
        public int Irrelevant { get; set; }
    }

    private sealed class AreaStats
    {
        [System.Text.Json.Serialization.JsonPropertyName("mean")]
        public double Mean { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("median")]
        public double Median { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("std")]
        public double Std { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("cv_percent")]
        public double CvPercent { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("min")]
        public double Min { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("max")]
        public double Max { get; set; }

        [System.Text.Json.Serialization.JsonPropertyName("total_coverage")]
        public double TotalCoverage { get; set; }
    }

    private sealed class ClassDistribution
    {
        public ClassStats? Background { get; set; }
        public ClassStats? Healthy { get; set; }
        public ClassStats? Affected { get; set; }
        public ClassStats? Irrelevant { get; set; }
    }

    private sealed class ClassStats
    {
        public int Pixels { get; set; }
        public double Percent { get; set; }
    }

    private sealed class ProgressInfo
    {
        public string? Step { get; set; }
        public int Percent { get; set; }
        public string? Message { get; set; }
    }

    private sealed record ProcessedImageRecord(string FileName, DateTime ProcessedAt, int CellCount);

    // =========================================================================
    // History Feature - Data Classes
    // =========================================================================
    public sealed class HistoryEntry
    {
        public string Id { get; set; } = Guid.NewGuid().ToString();
        public string FileName { get; set; } = "";
        public string OriginalFilePath { get; set; } = "";
        public DateTime ProcessedAt { get; set; }
        public int TotalCells { get; set; }
        public int HealthyCells { get; set; }
        public int AffectedCells { get; set; }
        public int IrrelevantCells { get; set; }
        public double MeanCellArea { get; set; }
        public double MedianCellArea { get; set; }
        public string? OverlayImagePath { get; set; }
        public string? ThumbnailPath { get; set; }
        public string? ResultsJson { get; set; }
    }

    public sealed class HistoryData
    {
        public List<HistoryEntry> Entries { get; set; } = new();
        public DateTime LastUpdated { get; set; }
    }

    public class HistoryManager
    {
        private readonly string _historyFilePath;
        private readonly string _historyFolderPath;
        private HistoryData _data = new();

        public HistoryManager()
        {
            var baseDir = AppDomain.CurrentDomain.BaseDirectory;
            _historyFilePath = Path.Combine(baseDir, "history.json");
            _historyFolderPath = Path.Combine(baseDir, "history_images");

            Directory.CreateDirectory(_historyFolderPath);
            LoadHistory();
        }

        public void LoadHistory()
        {
            if (File.Exists(_historyFilePath))
            {
                try
                {
                    var json = File.ReadAllText(_historyFilePath);
                    _data = JsonSerializer.Deserialize<HistoryData>(json,
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? new();
                }
                catch { _data = new(); }
            }
        }

        public void SaveHistory()
        {
            _data.LastUpdated = DateTime.Now;
            var json = JsonSerializer.Serialize(_data, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(_historyFilePath, json);
        }

        public string AddEntry(HistoryEntry entry, string? overlayImagePath = null)
        {
            // Copy images to history folder
            if (!string.IsNullOrEmpty(overlayImagePath) && File.Exists(overlayImagePath))
            {
                var destName = $"{entry.Id}_overlay.png";
                var destPath = Path.Combine(_historyFolderPath, destName);
                File.Copy(overlayImagePath, destPath, true);
                entry.OverlayImagePath = destName;

                // Generate thumbnail
                var thumbName = $"{entry.Id}_thumb.png";
                var thumbPath = Path.Combine(_historyFolderPath, thumbName);
                CreateThumbnail(overlayImagePath, thumbPath, 150, 150);
                entry.ThumbnailPath = thumbName;
            }

            _data.Entries.Insert(0, entry); // Most recent first
            SaveHistory();
            return entry.Id;
        }

        public List<HistoryEntry> GetAllEntries() => _data.Entries;

        public List<HistoryEntry> SearchEntries(string? filename = null,
                                                 DateTime? fromDate = null,
                                                 DateTime? toDate = null)
        {
            var query = _data.Entries.AsEnumerable();

            if (!string.IsNullOrEmpty(filename))
                query = query.Where(e => e.FileName.Contains(filename, StringComparison.OrdinalIgnoreCase));
            if (fromDate.HasValue)
                query = query.Where(e => e.ProcessedAt >= fromDate.Value);
            if (toDate.HasValue)
                query = query.Where(e => e.ProcessedAt <= toDate.Value.AddDays(1));

            return query.ToList();
        }

        public bool DeleteEntry(string id)
        {
            var entry = _data.Entries.FirstOrDefault(e => e.Id == id);
            if (entry == null) return false;

            // Delete associated images
            if (!string.IsNullOrEmpty(entry.OverlayImagePath))
            {
                var path = Path.Combine(_historyFolderPath, entry.OverlayImagePath);
                if (File.Exists(path)) File.Delete(path);
            }
            if (!string.IsNullOrEmpty(entry.ThumbnailPath))
            {
                var path = Path.Combine(_historyFolderPath, entry.ThumbnailPath);
                if (File.Exists(path)) File.Delete(path);
            }

            _data.Entries.Remove(entry);
            SaveHistory();
            return true;
        }

        public void ClearAll()
        {
            foreach (var entry in _data.Entries.ToList())
            {
                DeleteEntry(entry.Id);
            }
        }

        public string GetImageFullPath(string relativePath)
        {
            return Path.Combine(_historyFolderPath, relativePath);
        }

        private static void CreateThumbnail(string sourcePath, string destPath, int maxWidth, int maxHeight)
        {
            try
            {
                var source = new BitmapImage();
                source.BeginInit();
                source.UriSource = new Uri(sourcePath);
                source.CacheOption = BitmapCacheOption.OnLoad;
                source.EndInit();

                double scale = Math.Min((double)maxWidth / source.PixelWidth, (double)maxHeight / source.PixelHeight);
                var target = new TransformedBitmap(source, new ScaleTransform(scale, scale));

                var encoder = new PngBitmapEncoder();
                encoder.Frames.Add(BitmapFrame.Create(target));
                using var fs = new FileStream(destPath, FileMode.Create);
                encoder.Save(fs);
            }
            catch
            {
                // If thumbnail creation fails, just skip it
            }
        }
    }

    private static string FindPythonExecutable()
    {
        // Try common Python locations
        var candidates = new[]
        {
            "python",  // From PATH
            "python3", // From PATH (Linux/Mac)
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Microsoft", "WindowsApps", "python.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "Python", "Python311", "python.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "Python", "Python310", "python.exe"),
            @"C:\Python311\python.exe",
            @"C:\Python310\python.exe",
        };

        foreach (var candidate in candidates)
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = candidate,
                    Arguments = "--version",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                using var process = Process.Start(psi);
                if (process is not null)
                {
                    process.WaitForExit(3000);
                    if (process.ExitCode == 0)
                    {
                        return candidate;
                    }
                }
            }
            catch
            {
                // Try next candidate
            }
        }

        return "python"; // Fallback to PATH
    }

    public MainWindow(string? username = null, bool isGuest = true)
    {
        InitializeComponent();
        MetricsItemsControl.ItemsSource = _metrics;

        _currentUsername = username;
        _isGuest = isGuest;

        _pythonExecutable = FindPythonExecutable();
        _scriptPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "process_images.py");
        Loaded += async (_, _) => await InitializeAsync();

        // Update window title with user info
        Title = _isGuest
            ? "Cell Morphology Studio - Guest Mode"
            : $"Cell Morphology Studio - {_currentUsername}";

        // Handle window close to properly shutdown app
        Closed += (_, _) => Application.Current.Shutdown();
    }

    private Task InitializeAsync()
    {
        if (!File.Exists(_scriptPath))
        {
            ShowError("process_images.py is missing in the application folder.");
        }

        return Task.CompletedTask;
    }

    private async void PredictButton_Click(object sender, RoutedEventArgs e)
    {
        if (!EnsureSampleReady())
        {
            return;
        }

        await RunPredictionSuiteAsync();
    }

    private void SelectSampleButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select microscopy image",
            Filter = "Image files|*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp|All files|*.*"
        };

        if (dialog.ShowDialog() == true)
        {
            LoadImageFile(dialog.FileName);
        }
    }

    private void NewImageButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select new microscopy image",
            Filter = "Image files|*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp|All files|*.*"
        };

        if (dialog.ShowDialog() == true)
        {
            // Reset UI state
            ResetAnalysisState();
            // Load new image
            LoadImageFile(dialog.FileName);
        }
    }

    private void ResetAnalysisState()
    {
        // Clear previous results
        _lastResults = null;

        // Reset image zoom to 1x
        ResetImageZoom();

        // Reset images
        OverlayImage.Source = null;
        MaskImage.Source = null;
        CellCountImage.Source = null;
        CellAreaImage.Source = null;
        KdeHistogramImage.Source = null;
        BoxplotImage.Source = null;
        CumulativeImage.Source = null;
        PieChartImage.Source = null;

        // Reset metrics
        _metrics.Clear();

        // Reset class distribution bars
        HealthyPercentText.Text = "--%";
        AffectedPercentText.Text = "--%";
        IrrelevantPercentText.Text = "--%";
        HealthyBar.Width = 0;
        AffectedBar.Width = 0;
        IrrelevantBar.Width = 0;

        // Reset progress
        AnalysisProgressBar.Value = 0;
        ProgressText.Text = "";

        // Disable buttons that require analysis results
        ExportButton.IsEnabled = false;
        GenerateReportButton.IsEnabled = false;
        LabelEditorButton.IsEnabled = false;
        MeasureButton.IsEnabled = false;

        // ROI will be enabled after image loads (in UpdateActionButtons)

        // Reset status
        HeadlineText.Text = "New sample";
        SummaryText.Text = "Ready to analyze.";
        StatusMessageText.Text = "Ready";
        StatusSummaryText.Text = "New image loaded";
    }

    private void DisplayUploadedSample(string path)
    {
        var source = LoadImage(path);
        if (source is null)
        {
            return;
        }

        OriginalImage.Source = source;
        ImageTabControl.SelectedIndex = 0; // Select Original tab
    }

    private bool EnsureSampleReady()
    {
        if (_sampleReady)
        {
            return true;
        }

        System.Windows.MessageBox.Show("Please upload a microscopy image first.", "Sample required", MessageBoxButton.OK, MessageBoxImage.Information);
        return false;
    }

    private async Task RunPredictionSuiteAsync()
    {
        SetBusyState(true, "Predict");
        try
        {
            var results = await Task.Run(() => ExecuteActionSuite());
            ApplyCombinedResults(results);
        }
        catch (Exception ex)
        {
            ShowError(ex.Message);
        }
        finally
        {
            SetBusyState(false);
        }
    }

    private ActionResult ExecuteAction(string action, bool generatePdf = false)
    {
        var psi = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        psi.ArgumentList.Add(_scriptPath);
        psi.ArgumentList.Add("--action");
        psi.ArgumentList.Add(action);
        psi.ArgumentList.Add("--json");
        if (generatePdf)
        {
            psi.ArgumentList.Add("--pdf");
        }

        using var process = Process.Start(psi);
        if (process is null)
        {
            throw new InvalidOperationException("Unable to start the Python process.");
        }

        // Read stderr for progress updates
        var stderrLines = new List<string>();
        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            stderrLines.Add(e.Data);

            // Parse progress updates
            if (e.Data.StartsWith("PROGRESS:"))
            {
                try
                {
                    var json = e.Data.Substring(9);
                    var progress = JsonSerializer.Deserialize<ProgressInfo>(json,
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                    if (progress is not null)
                    {
                        Dispatcher.BeginInvoke(() => UpdateProgress(progress));
                    }
                }
                catch { /* Ignore parse errors */ }
            }
        };
        process.BeginErrorReadLine();

        var stdout = process.StandardOutput.ReadToEnd();
        process.WaitForExit();

        if (process.ExitCode != 0)
        {
            // Only consider lines starting with ERROR: as actual errors
            var errorLines = stderrLines.Where(l => l.StartsWith("ERROR:")).ToList();
            if (errorLines.Count > 0)
            {
                var message = string.Join(Environment.NewLine, errorLines.Select(l => l.Substring(6).Trim()));
                throw new InvalidOperationException(message);
            }
            else
            {
                // Fallback: filter out progress and info messages
                var otherErrors = stderrLines.Where(l =>
                    !l.StartsWith("PROGRESS:") &&
                    !l.StartsWith("Using device:") &&
                    !l.Contains("FutureWarning") &&
                    !l.Contains("loaded successfully") &&
                    !l.Contains("skipping") &&
                    !string.IsNullOrWhiteSpace(l)
                ).ToList();

                var message = otherErrors.Count > 0
                    ? string.Join(Environment.NewLine, otherErrors)
                    : "Python script returned an error.";
                throw new InvalidOperationException(message);
            }
        }

        // Parse JSON results
        if (!string.IsNullOrWhiteSpace(stdout))
        {
            try
            {
                _lastResults = JsonSerializer.Deserialize<AnalysisResults>(stdout,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            }
            catch { /* Fallback to file-based results */ }
        }

        // Also try to load from results.json file
        if (_lastResults is null)
        {
            var resultsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "results.json");
            if (File.Exists(resultsPath))
            {
                try
                {
                    var json = File.ReadAllText(resultsPath);
                    _lastResults = JsonSerializer.Deserialize<AnalysisResults>(json,
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                }
                catch { /* Ignore */ }
            }
        }

        // For "all" action, don't build result here - it's handled by ExecuteActionSuite
        if (action == "all")
        {
            return new ActionResult { Action = "all" };
        }

        return BuildActionResult(action);
    }

    private void UpdateProgress(ProgressInfo progress)
    {
        // Update left panel
        StatusMessageText.Text = progress.Step ?? "Processing";
        StatusSummaryText.Text = progress.Message ?? "Working...";
        ProgressText.Text = progress.Message ?? "";
        AnalysisProgressBar.Value = progress.Percent;
        AnalysisProgressBar.IsIndeterminate = false;

        // Update spinning wheel overlay text
        BusyStatusText.Text = progress.Step ?? "Processing";
        BusyDetailText.Text = $"{progress.Message ?? "Working..."} ({progress.Percent}%)";
    }

    private void UpdateClassDistributionUI()
    {
        if (_lastResults?.Statistics?.ClassDistribution is null)
        {
            HealthyPercentText.Text = "--%";
            AffectedPercentText.Text = "--%";
            IrrelevantPercentText.Text = "--%";
            HealthyBar.Width = 0;
            AffectedBar.Width = 0;
            IrrelevantBar.Width = 0;
            return;
        }

        var dist = _lastResults.Statistics.ClassDistribution;
        const double maxWidth = 280; // Max bar width

        if (dist.Healthy is not null)
        {
            HealthyPercentText.Text = $"{dist.Healthy.Percent:F1}%";
            HealthyBar.Width = (dist.Healthy.Percent / 100.0) * maxWidth;
        }
        if (dist.Affected is not null)
        {
            AffectedPercentText.Text = $"{dist.Affected.Percent:F1}%";
            AffectedBar.Width = (dist.Affected.Percent / 100.0) * maxWidth;
        }
        if (dist.Irrelevant is not null)
        {
            IrrelevantPercentText.Text = $"{dist.Irrelevant.Percent:F1}%";
            IrrelevantBar.Width = (dist.Irrelevant.Percent / 100.0) * maxWidth;
        }
    }

    private void UpdateSessionUI()
    {
        TotalProcessedText.Text = _totalProcessed.ToString();
        if (_processedHistory.Count > 0)
        {
            var last = _processedHistory[^1];
            LastFileText.Text = $"Last: {last.FileName}";
        }
    }

    // Drag & Drop handlers
    private void OnboardingOverlay_DragEnter(object sender, System.Windows.DragEventArgs e)
    {
        if (e.Data.GetDataPresent(System.Windows.DataFormats.FileDrop))
        {
            e.Effects = System.Windows.DragDropEffects.Copy;
            DropZone.BorderBrush = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#6B4E71"));
            DropZone.Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#BDB2C4"));
        }
        else
        {
            e.Effects = System.Windows.DragDropEffects.None;
        }
        e.Handled = true;
    }

    private void OnboardingOverlay_DragLeave(object sender, System.Windows.DragEventArgs e)
    {
        DropZone.BorderBrush = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#D1CCD6"));
        DropZone.Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#F3EFF5"));
    }

    private void OnboardingOverlay_Drop(object sender, System.Windows.DragEventArgs e)
    {
        DropZone.BorderBrush = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#D1CCD6"));
        DropZone.Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#F3EFF5"));

        if (!e.Data.GetDataPresent(System.Windows.DataFormats.FileDrop)) return;

        var files = (string[]?)e.Data.GetData(System.Windows.DataFormats.FileDrop);
        if (files is null || files.Length == 0) return;

        var file = files[0];
        var ext = Path.GetExtension(file).ToLower();
        var validExtensions = new[] { ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp" };

        if (!validExtensions.Contains(ext))
        {
            ShowError("Please drop a valid image file (PNG, JPG, TIF, BMP).");
            return;
        }

        LoadImageFile(file);
    }

    private void LoadImageFile(string filePath)
    {
        try
        {
            var destination = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "original.png");
            var inputCopy = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "input.jpg");
            File.Copy(filePath, destination, overwrite: true);
            File.Copy(filePath, inputCopy, overwrite: true);
            _uploadedSamplePath = filePath;
            _sampleReady = true;
            OnboardingOverlay.Visibility = Visibility.Collapsed;
            DisplayUploadedSample(destination);
            HeadlineText.Text = "Sample loaded";
            SummaryText.Text = "Run prediction to generate outputs.";
            StatusMessageText.Text = "Ready";
            StatusSummaryText.Text = Path.GetFileName(filePath);
            UpdateActionButtons();
        }
        catch (Exception ex)
        {
            ShowError($"Failed to load file: {ex.Message}");
        }
    }

    // Batch processing
    private async void BatchButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "Select folder containing microscopy images",
            ShowNewFolderButton = false
        };

        if (dialog.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;

        var inputFolder = dialog.SelectedPath;

        // Ask for output folder
        var outputDialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "Select output folder for results",
            ShowNewFolderButton = true
        };

        string? outputFolder = null;
        if (outputDialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
        {
            outputFolder = outputDialog.SelectedPath;
        }

        SetBusyState(true, "Batch");
        AnalysisProgressBar.IsIndeterminate = true;

        try
        {
            await Task.Run(() => ExecuteBatchProcessing(inputFolder, outputFolder));

            System.Windows.MessageBox.Show($"Batch processing completed!\nResults saved to: {outputFolder ?? Path.Combine(inputFolder, "results")}",
                           "Batch Complete", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            ShowError($"Batch processing failed: {ex.Message}");
        }
        finally
        {
            SetBusyState(false);
            AnalysisProgressBar.IsIndeterminate = false;
            AnalysisProgressBar.Value = 0;
        }
    }

    private void ExecuteBatchProcessing(string inputFolder, string? outputFolder)
    {
        var psi = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        psi.ArgumentList.Add(_scriptPath);
        psi.ArgumentList.Add("--batch");
        psi.ArgumentList.Add(inputFolder);
        if (!string.IsNullOrEmpty(outputFolder))
        {
            psi.ArgumentList.Add("--output");
            psi.ArgumentList.Add(outputFolder);
        }
        psi.ArgumentList.Add("--pdf");
        psi.ArgumentList.Add("--json");

        using var process = Process.Start(psi);
        if (process is null)
        {
            throw new InvalidOperationException("Unable to start batch processing.");
        }

        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is null) return;
            if (e.Data.StartsWith("PROGRESS:"))
            {
                try
                {
                    var json = e.Data.Substring(9);
                    var progress = JsonSerializer.Deserialize<ProgressInfo>(json,
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                    if (progress is not null)
                    {
                        Dispatcher.BeginInvoke(() => UpdateProgress(progress));
                    }
                }
                catch { }
            }
        };
        process.BeginErrorReadLine();
        process.WaitForExit();

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException("Batch processing failed.");
        }
    }

    // Export results
    private void ExportButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "Select folder to save results",
            ShowNewFolderButton = true
        };

        if (dialog.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;

        try
        {
            var outputFolder = dialog.SelectedPath;
            var baseDir = AppDomain.CurrentDomain.BaseDirectory;

            // Files to export
            var filesToExport = new[]
            {
                "original.png", "overlay_predict.png", "prediction_result_predict.png",
                "cell_count.png", "cell_count.txt", "cell_area.png", "cell_area.txt",
                "1_cell_area_distribution_kde.png", "2_cell_area_boxplot.png",
                "3_cell_area_cumulative.png", "4_cell_size_categories.png",
                "results.json", "report.pdf"
            };

            var exportedCount = 0;
            foreach (var file in filesToExport)
            {
                var source = Path.Combine(baseDir, file);
                if (File.Exists(source))
                {
                    var dest = Path.Combine(outputFolder, file);
                    File.Copy(source, dest, overwrite: true);
                    exportedCount++;
                }
            }

            System.Windows.MessageBox.Show($"Exported {exportedCount} files to:\n{outputFolder}",
                           "Export Complete", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            ShowError($"Export failed: {ex.Message}");
        }
    }

    private void ApplyCombinedResults(IEnumerable<ActionResult> results)
    {
        var list = results.ToList();
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;

        // Populate image tabs
        OriginalImage.Source = LoadImage(Path.Combine(baseDir, "original.png"));
        OverlayImage.Source = LoadImage(Path.Combine(baseDir, "overlay_predict.png"));
        MaskImage.Source = LoadImage(Path.Combine(baseDir, "prediction_result_predict.png"));
        CellCountImage.Source = LoadImage(Path.Combine(baseDir, "cell_count.png"));
        CellAreaImage.Source = LoadImage(Path.Combine(baseDir, "cell_area.png"));

        // Populate histogram images
        KdeHistogramImage.Source = LoadImage(Path.Combine(baseDir, "1_cell_area_distribution_kde.png"));
        BoxplotImage.Source = LoadImage(Path.Combine(baseDir, "2_cell_area_boxplot.png"));
        CumulativeImage.Source = LoadImage(Path.Combine(baseDir, "3_cell_area_cumulative.png"));
        PieChartImage.Source = LoadImage(Path.Combine(baseDir, "4_cell_size_categories.png"));

        // Select Overlay tab to show results
        ImageTabControl.SelectedIndex = 1;

        // Build metrics from JSON results if available
        _metrics.Clear();

        if (_lastResults?.Statistics is not null)
        {
            var stats = _lastResults.Statistics;
            var totalCells = stats.TotalCells > 0 ? stats.TotalCells : stats.CellCount;

            // Cell counts - main metrics
            _metrics.Add(new MetricViewModel("Total Cells", totalCells.ToString(), "#E8E4EC"));

            if (stats.CellCountsByClass is not null)
            {
                var counts = stats.CellCountsByClass;
                _metrics.Add(new MetricViewModel("Healthy", counts.Healthy.ToString(), "#D4EDDA"));
                _metrics.Add(new MetricViewModel("Affected", counts.Affected.ToString(), "#F8D7DA"));
                if (counts.Irrelevant > 0)
                    _metrics.Add(new MetricViewModel("Irrelevant", counts.Irrelevant.ToString(), "#FFF3CD"));
            }

            // Area statistics
            if (stats.AreaStats is not null)
            {
                var area = stats.AreaStats;
                _metrics.Add(new MetricViewModel("Mean Area", $"{area.Mean:F0} px²", "#F3EFF5"));
                _metrics.Add(new MetricViewModel("Median", $"{area.Median:F0} px²", "#F3EFF5"));
                _metrics.Add(new MetricViewModel("CV%", $"{area.CvPercent:F1}%", "#F3EFF5"));
            }
        }
        else
        {
            // Fallback to file-based metrics
            foreach (var m in list.SelectMany(r => r.Metrics))
            {
                if (string.IsNullOrWhiteSpace(m.Label) || string.IsNullOrWhiteSpace(m.Value))
                    continue;
                _metrics.Add(new MetricViewModel(m.Label, m.Value));
            }
        }

        // Update session state
        _totalProcessed++;
        var fileName = _lastResults?.InputFile ?? Path.GetFileName(_uploadedSamplePath ?? "unknown");
        var cellCount2 = _lastResults?.Statistics?.CellCount ?? _lastResults?.Statistics?.TotalCells ?? 0;
        _processedHistory.Add(new ProcessedImageRecord(fileName, DateTime.Now, cellCount2));

        // Update UI with session stats
        HeadlineText.Text = "Prediction ready";
        SummaryText.Text = $"Analysis completed. Total processed: {_totalProcessed}";
        StatusMessageText.Text = "Complete";
        StatusSummaryText.Text = $"Last: {fileName}";

        // Update class distribution bars and session UI
        UpdateClassDistributionUI();
        UpdateSessionUI();

        // Reset progress bar
        AnalysisProgressBar.Value = 100;
        ProgressText.Text = "Analysis complete";

        // Enable buttons that require analysis results
        ExportButton.IsEnabled = true;
        GenerateReportButton.IsEnabled = true;
        LabelEditorButton.IsEnabled = true;
        MeasureButton.IsEnabled = true;

        // Save to persistent history
        try
        {
            var historyEntry = new HistoryEntry
            {
                FileName = fileName,
                OriginalFilePath = _uploadedSamplePath ?? "",
                ProcessedAt = DateTime.Now,
                TotalCells = _lastResults?.Statistics?.TotalCells ?? _lastResults?.Statistics?.CellCount ?? 0,
                HealthyCells = _lastResults?.Statistics?.CellCountsByClass?.Healthy ?? 0,
                AffectedCells = _lastResults?.Statistics?.CellCountsByClass?.Affected ?? 0,
                IrrelevantCells = _lastResults?.Statistics?.CellCountsByClass?.Irrelevant ?? 0,
                MeanCellArea = _lastResults?.Statistics?.AreaStats?.Mean ?? _lastResults?.Statistics?.MeanCellArea ?? 0,
                MedianCellArea = _lastResults?.Statistics?.AreaStats?.Median ?? 0,
                ResultsJson = _lastResults != null
                    ? JsonSerializer.Serialize(_lastResults, new JsonSerializerOptions { WriteIndented = false })
                    : null
            };

            var overlayPath = Path.Combine(baseDir, "overlay_predict.png");
            _historyManager.AddEntry(historyEntry, overlayPath);
        }
        catch
        {
            // History save failed, but don't interrupt the user
        }
    }


    private static ImageSource? LoadImage(string path)
    {
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.UriSource = new Uri(path, UriKind.Absolute);
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.CreateOptions = BitmapCreateOptions.IgnoreImageCache; // Force refresh
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
        catch
        {
            return null;
        }
    }


    private void SetBusyState(bool isBusy, string? status = null)
    {
        _isBusy = isBusy;
        BusyOverlay.Visibility = isBusy ? Visibility.Visible : Visibility.Collapsed;
        UpdateActionButtons();

        if (isBusy)
        {
            // Update left panel status
            StatusMessageText.Text = status ?? "Processing";
            StatusSummaryText.Text = "Analysis in progress...";
            AnalysisProgressBar.Value = 0;
            AnalysisProgressBar.IsIndeterminate = true;
            ProgressText.Text = "Starting...";

            // Update spinning wheel text
            BusyStatusText.Text = status ?? "Processing";
            BusyDetailText.Text = "Analysis in progress...";
        }
        else
        {
            AnalysisProgressBar.IsIndeterminate = false;
        }
    }

    private void UpdateActionButtons()
    {
        var enabled = _sampleReady && !_isBusy;
        PredictButton.IsEnabled = enabled;
        ROIButton.IsEnabled = enabled; // ROI can be used before analysis
    }

    private static string GetModeLabel(string? mode) => mode switch
    {
        "predict" => "Predict",
        "cell" => "Cell count",
        "cell_area" => "Cell area",
        _ => "Pipeline"
    };

    private void ShowError(string message)
    {
        BusyOverlay.Visibility = Visibility.Collapsed;
        _isBusy = false;
        UpdateActionButtons();
        System.Windows.MessageBox.Show(message, "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        StatusMessageText.Text = "Error";
        StatusSummaryText.Text = message;
        SummaryText.Text = message;
    }


    private sealed record MetricViewModel(string Label, string Value, string Background = "#F3EFF5");

    private sealed class ActionResult
    {
        public required string Action { get; init; }
        public DisplayImagePayload? PrimaryImage { get; init; }
        public List<DisplayImagePayload> Gallery { get; init; } = new();
        public List<MetricPayload> Metrics { get; init; } = new();
        public string? HistogramPath { get; init; }
    }

    private sealed class DisplayImagePayload
    {
        public string? Label { get; set; }
        public string? Description { get; set; }
        public string? Path { get; set; }
    }

    private sealed class MetricPayload
    {
        public string? Label { get; set; }
        public string? Value { get; set; }
    }

    private List<ActionResult> ExecuteActionSuite(bool generatePdf = true)
    {
        // Run all actions with single Python call (single inference)
        // generatePdf=true will create a PDF report
        ExecuteAction("all", generatePdf);

        // Build results from generated files
        var actions = new[] { "predict", "cell", "cell_area" };
        var results = new List<ActionResult>();
        foreach (var action in actions)
        {
            results.Add(BuildActionResult(action));
        }
        return results;
    }

    private ActionResult BuildActionResult(string action)
    {
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;
        DisplayImagePayload? primary = null;
        var gallery = new List<DisplayImagePayload>();
        var metrics = new List<MetricPayload>();
        string? histogramPath = null;
        var inputPath = Path.Combine(baseDir, "input.jpg");

        DisplayImagePayload? AddImage(string fileName, string label, string? description = null)
        {
            var path = Path.Combine(baseDir, fileName);
            if (!File.Exists(path))
            {
                return null;
            }

            var payload = new DisplayImagePayload
            {
                Label = label,
                Description = description,
                Path = path
            };

            gallery.Add(payload);
            return payload;
        }

        switch (action)
        {
            case "predict":
                AddImage("original.png", "Original");
                var overlay = AddImage("overlay_predict.png", "Segmentation overlay");
                var mask = AddImage("prediction_result_predict.png", "Mask (argmax)");
                primary = overlay ?? mask ?? primary;
                break;
            case "cell":
                AddImage("original.png", "Original");
                var overlayCell = AddImage("overlay_cell.png", "Overlay (cell)");
                if (overlayCell is null)
                {
                    AddImage("overlay_predict.png", "Segmentation overlay");
                }
                primary = AddImage("cell_count.png", "Cell count view");
                var maskCell = AddImage("prediction_result_cell.png", "Mask (cell class)");
                if (primary is null)
                {
                    primary = maskCell;
                }

                var cellCountPath = Path.Combine(baseDir, "cell_count.txt");
                if (File.Exists(cellCountPath))
                {
                    var text = File.ReadAllText(cellCountPath);
                    if (int.TryParse(text.Trim(), out var count))
                    {
                        metrics.Add(new MetricPayload { Label = "Cell count", Value = count.ToString() });
                    }
                }

                histogramPath = gallery.FirstOrDefault(g => g.Path?.Contains("cell_count") == true)?.Path;
                break;
            case "cell_area":
                AddImage("original.png", "Original");
                var overlayArea = AddImage("overlay_cell_area.png", "Overlay (cell area)");
                if (overlayArea is null)
                {
                    AddImage("overlay_predict.png", "Segmentation overlay");
                }
                primary = AddImage("cell_area.png", "Cell area visualization");
                var maskArea = AddImage("prediction_result_cell_area.png", "Class mask");
                if (primary is null)
                {
                    primary = maskArea;
                }

                string[] extraPlots =
                {
                    "1_cell_area_distribution_kde.png",
                    "2_cell_area_boxplot.png",
                    "3_cell_area_cumulative.png",
                    "4_cell_size_categories.png"
                };
                foreach (var plot in extraPlots)
                {
                    AddImage(plot, Path.GetFileNameWithoutExtension(plot)?.Replace("_", " ") ?? "Plot");
                }

                var areaTxt = Path.Combine(baseDir, "cell_area.txt");
                if (File.Exists(areaTxt))
                {
                    var lines = File.ReadAllLines(areaTxt);
                    var totalLine = lines.FirstOrDefault(l => l.Contains("Total Cells", StringComparison.OrdinalIgnoreCase));
                    if (totalLine is not null)
                    {
                        var parts = totalLine.Split(':');
                        if (parts.Length > 1)
                        {
                            metrics.Add(new MetricPayload { Label = "Total cells", Value = parts[1].Trim() });
                        }
                    }
                }

                histogramPath = gallery.FirstOrDefault(g => g.Path?.Contains("distribution_kde") == true)?.Path;
                break;
            default:
                throw new InvalidOperationException($"Unsupported action '{action}'.");
        }

        return new ActionResult
        {
            Action = action,
            PrimaryImage = primary,
            Gallery = gallery,
            Metrics = metrics,
            HistogramPath = histogramPath
        };
    }

    // =========================================================================
    // Image Popup Handlers
    // =========================================================================
    private double _popupZoomLevel = 1.0;
    private const double MinZoom = 0.5;
    private const double MaxZoom = 5.0;

    private void HistogramImage_Click(object sender, MouseButtonEventArgs e)
    {
        if (sender is System.Windows.Controls.Image img && img.Source != null)
        {
            PopupImage.Source = img.Source;
            PopupTitle.Text = img.Tag?.ToString() ?? "Analysis Plot";
            _popupZoomLevel = 1.0;
            PopupImageScale.ScaleX = 1.0;
            PopupImageScale.ScaleY = 1.0;
            ImagePopupOverlay.Visibility = Visibility.Visible;
        }
    }

    private void PopupCloseButton_Click(object sender, RoutedEventArgs e)
    {
        ImagePopupOverlay.Visibility = Visibility.Collapsed;
    }

    private void ImagePopupOverlay_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        // Close popup when clicking outside the image container
        if (e.OriginalSource is System.Windows.Controls.Border border)
        {
            // Check if clicked on the dark overlay background (not the popup container)
            if (border != PopupContainer && !IsChildOf(border, PopupContainer))
            {
                ImagePopupOverlay.Visibility = Visibility.Collapsed;
            }
        }
    }

    private static bool IsChildOf(DependencyObject child, DependencyObject parent)
    {
        var current = child;
        while (current != null)
        {
            if (current == parent) return true;
            current = VisualTreeHelper.GetParent(current);
        }
        return false;
    }

    private void PopupImageContainer_MouseWheel(object sender, MouseWheelEventArgs e)
    {
        // Zoom with mouse wheel
        double zoomDelta = e.Delta > 0 ? 0.1 : -0.1;
        _popupZoomLevel = Math.Clamp(_popupZoomLevel + zoomDelta, MinZoom, MaxZoom);

        PopupImageScale.ScaleX = _popupZoomLevel;
        PopupImageScale.ScaleY = _popupZoomLevel;

        e.Handled = true;
    }

    // =========================================================================
    // History Panel Handlers
    // =========================================================================
    private void HistoryButton_Click(object sender, RoutedEventArgs e)
    {
        RefreshHistoryView();
        HistoryPanel.Visibility = Visibility.Visible;
    }

    private void CloseHistoryButton_Click(object sender, RoutedEventArgs e)
    {
        HistoryPanel.Visibility = Visibility.Collapsed;
    }

    private void RefreshHistoryView()
    {
        var searchText = HistorySearchBox?.Text;
        var fromDate = FromDatePicker?.SelectedDate;
        var toDate = ToDatePicker?.SelectedDate;

        var entries = _historyManager.SearchEntries(searchText, fromDate, toDate);

        // Map to view model with full paths
        var viewModels = entries.Select(e => new HistoryEntryViewModel(e, _historyManager)).ToList();

        HistoryListView.ItemsSource = viewModels;
        HistoryGalleryItems.ItemsSource = viewModels;
    }

    private void ListViewToggle_Click(object sender, RoutedEventArgs e)
    {
        ListViewToggle.Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#6B4E71"));
        GalleryViewToggle.Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#BDB2C4"));
        HistoryListView.Visibility = Visibility.Visible;
        HistoryGalleryView.Visibility = Visibility.Collapsed;
    }

    private void GalleryViewToggle_Click(object sender, RoutedEventArgs e)
    {
        GalleryViewToggle.Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#6B4E71"));
        ListViewToggle.Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#BDB2C4"));
        HistoryListView.Visibility = Visibility.Collapsed;
        HistoryGalleryView.Visibility = Visibility.Visible;
    }

    private void HistorySearchBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        RefreshHistoryView();
    }

    private void DateFilter_Changed(object sender, SelectionChangedEventArgs e)
    {
        RefreshHistoryView();
    }

    private void LoadHistoryEntry_Click(object sender, RoutedEventArgs e)
    {
        if (sender is System.Windows.Controls.Button btn && btn.Tag is string id)
        {
            var entry = _historyManager.GetAllEntries().FirstOrDefault(x => x.Id == id);
            if (entry != null)
            {
                LoadHistoryEntryIntoView(entry);
                HistoryPanel.Visibility = Visibility.Collapsed;
            }
        }
    }

    private void LoadHistoryEntryIntoView(HistoryEntry entry)
    {
        // Load overlay image
        if (!string.IsNullOrEmpty(entry.OverlayImagePath))
        {
            var fullPath = _historyManager.GetImageFullPath(entry.OverlayImagePath);
            OverlayImage.Source = LoadImage(fullPath);
            ImageTabControl.SelectedIndex = 1; // Overlay tab
        }

        // Restore results from JSON if available
        if (!string.IsNullOrEmpty(entry.ResultsJson))
        {
            try
            {
                _lastResults = JsonSerializer.Deserialize<AnalysisResults>(entry.ResultsJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                UpdateClassDistributionUI();
            }
            catch { /* Ignore deserialization errors */ }
        }

        // Update UI
        HeadlineText.Text = $"Loaded: {entry.FileName}";
        SummaryText.Text = $"From history ({entry.ProcessedAt:yyyy-MM-dd HH:mm})";

        // Update metrics
        _metrics.Clear();
        _metrics.Add(new MetricViewModel("Total Cells", entry.TotalCells.ToString()));
        _metrics.Add(new MetricViewModel("Healthy", entry.HealthyCells.ToString()));
        _metrics.Add(new MetricViewModel("Affected", entry.AffectedCells.ToString()));
        _metrics.Add(new MetricViewModel("Mean Area", $"{entry.MeanCellArea:F1} px"));
    }

    private void DeleteHistoryEntry_Click(object sender, RoutedEventArgs e)
    {
        if (sender is System.Windows.Controls.Button btn && btn.Tag is string id)
        {
            var result = System.Windows.MessageBox.Show("Delete this history entry?", "Confirm Delete",
                                     MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (result == MessageBoxResult.Yes)
            {
                _historyManager.DeleteEntry(id);
                RefreshHistoryView();
            }
        }
    }

    private void ClearHistoryButton_Click(object sender, RoutedEventArgs e)
    {
        var result = System.Windows.MessageBox.Show("Clear all history? This cannot be undone.", "Confirm Clear All",
                                 MessageBoxButton.YesNo, MessageBoxImage.Warning);
        if (result == MessageBoxResult.Yes)
        {
            _historyManager.ClearAll();
            RefreshHistoryView();
        }
    }

    private void GalleryItem_Click(object sender, MouseButtonEventArgs e)
    {
        if (sender is Border border && border.DataContext is HistoryEntryViewModel vm)
        {
            var entry = _historyManager.GetAllEntries().FirstOrDefault(x => x.Id == vm.Id);
            if (entry != null)
            {
                LoadHistoryEntryIntoView(entry);
                HistoryPanel.Visibility = Visibility.Collapsed;
            }
        }
    }

    // ViewModel for history data binding
    public class HistoryEntryViewModel
    {
        private readonly HistoryManager _manager;
        private readonly HistoryEntry _entry;

        public HistoryEntryViewModel(HistoryEntry entry, HistoryManager manager)
        {
            _entry = entry;
            _manager = manager;
        }

        public string Id => _entry.Id;
        public string FileName => _entry.FileName;
        public DateTime ProcessedAt => _entry.ProcessedAt;
        public int TotalCells => _entry.TotalCells;

        public string ThumbnailFullPath =>
            !string.IsNullOrEmpty(_entry.ThumbnailPath)
                ? _manager.GetImageFullPath(_entry.ThumbnailPath)
                : "";
    }

    // =========================================================================
    // AI Chat Panel Handlers
    // =========================================================================
    private void ChatButton_Click(object sender, RoutedEventArgs e)
    {
        ChatPanel.Visibility = Visibility.Visible;
    }

    private void CloseChatButton_Click(object sender, RoutedEventArgs e)
    {
        ChatPanel.Visibility = Visibility.Collapsed;
    }

    private async void SendChatButton_Click(object sender, RoutedEventArgs e)
    {
        await SendChatMessageAsync();
    }

    private async void ChatInputBox_KeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key == Key.Enter && !Keyboard.Modifiers.HasFlag(ModifierKeys.Shift))
        {
            e.Handled = true;
            await SendChatMessageAsync();
        }
    }

    private async Task SendChatMessageAsync()
    {
        var message = ChatInputBox.Text?.Trim();
        if (string.IsNullOrEmpty(message)) return;

        // Disable input while processing
        ChatInputBox.IsEnabled = false;
        SendChatButton.IsEnabled = false;
        ChatInputBox.Text = "";

        // Add user message to UI
        AddChatMessage(message, isUser: true);

        try
        {
            // Call Python chat handler
            var response = await Task.Run(() => ExecuteChatCommand("chat", message));
            AddChatMessage(response, isUser: false);
        }
        catch (Exception ex)
        {
            AddChatMessage($"Error: {ex.Message}", isUser: false);
        }
        finally
        {
            ChatInputBox.IsEnabled = true;
            SendChatButton.IsEnabled = true;
            ChatInputBox.Focus();
        }
    }

    private void AddChatMessage(string message, bool isUser)
    {
        var border = new Border
        {
            Background = new SolidColorBrush(isUser
                ? (System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#6B4E71")
                : (System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#F3EFF5")),
            CornerRadius = new CornerRadius(12),
            Padding = new Thickness(12, 8, 12, 8),
            Margin = new Thickness(isUser ? 40 : 0, 4, isUser ? 0 : 40, 4),
            HorizontalAlignment = isUser ? System.Windows.HorizontalAlignment.Right : System.Windows.HorizontalAlignment.Left,
            MaxWidth = 400
        };

        var textBlock = new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(isUser
                ? Colors.White
                : (System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#322935"))
        };

        border.Child = textBlock;
        ChatMessagesPanel.Children.Add(border);

        // Scroll to bottom
        ChatScrollViewer.ScrollToEnd();
    }

    private string ExecuteChatCommand(string command, string? message = null)
    {
        var chatScript = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "chat_handler.py");

        var psi = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        psi.ArgumentList.Add("-c");

        // Get base directory and remove trailing backslash for Python compatibility
        var baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');

        string pythonCode;
        if (command == "chat")
        {
            var escapedMessage = message?.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n") ?? "";
            pythonCode = $@"
import sys
import os
os.chdir(r'{baseDir}')
sys.path.insert(0, r'{baseDir}')
from chat_handler import ChatHandler
handler = ChatHandler()
if handler.is_available():
    print(handler.chat(""{escapedMessage}""))
else:
    print('AI chat not available. Please check API configuration.')
";
        }
        else if (command == "report")
        {
            pythonCode = $@"
import sys
import os
os.chdir(r'{baseDir}')
sys.path.insert(0, r'{baseDir}')
from chat_handler import ChatHandler
handler = ChatHandler()
if handler.is_available():
    print(handler.generate_report_interpretation())
else:
    print('AI not available.')
";
        }
        else if (command == "summary")
        {
            pythonCode = $@"
import sys
import os
os.chdir(r'{baseDir}')
sys.path.insert(0, r'{baseDir}')
from chat_handler import ChatHandler
handler = ChatHandler()
if handler.is_available():
    print(handler.get_quick_summary())
else:
    print('AI not available.')
";
        }
        else if (command == "clear")
        {
            pythonCode = $@"
import sys
import os
os.chdir(r'{baseDir}')
sys.path.insert(0, r'{baseDir}')
from chat_handler import ChatHandler
handler = ChatHandler()
handler.clear_history()
print('Chat history cleared.')
";
        }
        else
        {
            return "Unknown command";
        }

        psi.ArgumentList.Add(pythonCode);

        using var process = Process.Start(psi);
        if (process is null)
        {
            return "Failed to start Python process";
        }

        var output = process.StandardOutput.ReadToEnd();
        var error = process.StandardError.ReadToEnd();
        process.WaitForExit();

        if (!string.IsNullOrEmpty(error) && !error.Contains("Warning"))
        {
            // Filter out common non-error messages
            var errorLines = error.Split('\n')
                .Where(l => !string.IsNullOrWhiteSpace(l) &&
                           !l.Contains("Warning") &&
                           !l.Contains("FutureWarning"))
                .ToList();
            if (errorLines.Count > 0)
            {
                return $"Error: {string.Join(" ", errorLines)}";
            }
        }

        return output.Trim();
    }

    private async void QuickChat_ExplainResults(object sender, RoutedEventArgs e)
    {
        ChatInputBox.Text = "Can you explain the analysis results in detail?";
        await SendChatMessageAsync();
    }

    private async void QuickChat_Summary(object sender, RoutedEventArgs e)
    {
        ChatInputBox.IsEnabled = false;
        SendChatButton.IsEnabled = false;

        try
        {
            var summary = await Task.Run(() => ExecuteChatCommand("summary"));
            AddChatMessage("Give me a quick summary of the results.", isUser: true);
            AddChatMessage(summary, isUser: false);
        }
        catch (Exception ex)
        {
            AddChatMessage($"Error: {ex.Message}", isUser: false);
        }
        finally
        {
            ChatInputBox.IsEnabled = true;
            SendChatButton.IsEnabled = true;
        }
    }

    private void ClearChatButton_Click(object sender, RoutedEventArgs e)
    {
        ChatMessagesPanel.Children.Clear();
        Task.Run(() => ExecuteChatCommand("clear"));
    }

    // =========================================================================
    // AI Report Generation Handler
    // =========================================================================
    private async void GenerateReportButton_Click(object sender, RoutedEventArgs e)
    {
        if (_lastResults == null)
        {
            System.Windows.MessageBox.Show("Please run an analysis first.", "No Data",
                         MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        GenerateReportButton.IsEnabled = false;
        GenerateReportButton.Content = "Generating...";

        try
        {
            var reportPath = await Task.Run(() => GenerateAIReport());

            if (File.Exists(reportPath))
            {
                var result = System.Windows.MessageBox.Show(
                    $"Report generated successfully!\n\n{reportPath}\n\nWould you like to open it?",
                    "Report Ready",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Information);

                if (result == MessageBoxResult.Yes)
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = reportPath,
                        UseShellExecute = true
                    });
                }
            }
            else
            {
                System.Windows.MessageBox.Show("Report generation completed but file not found.",
                             "Warning", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show($"Failed to generate report: {ex.Message}",
                         "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            GenerateReportButton.IsEnabled = true;
            GenerateReportButton.Content = "Generate Report";
        }
    }

    // =========================================================================
    // Settings Panel Handlers
    // =========================================================================
    private bool _isDarkMode;
    private readonly AppSettings _appSettings = new();

    public sealed class AppSettings
    {
        public bool DarkMode { get; set; }
        public double Brightness { get; set; }
        public double Contrast { get; set; }
        public double Saturation { get; set; }
        public double Sharpness { get; set; }
        public double ConfidenceThreshold { get; set; } = 0.5;
        public double MinCellArea { get; set; } = 100;
        public double OverlayOpacity { get; set; } = 50;
        public string Language { get; set; } = "en";

        private static readonly string SettingsPath = Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory, "settings.json");

        public static AppSettings Load()
        {
            try
            {
                if (File.Exists(SettingsPath))
                {
                    var json = File.ReadAllText(SettingsPath);
                    return JsonSerializer.Deserialize<AppSettings>(json) ?? new AppSettings();
                }
            }
            catch { }
            return new AppSettings();
        }

        public void Save()
        {
            try
            {
                var json = JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true });
                File.WriteAllText(SettingsPath, json);
            }
            catch { }
        }
    }

    private void SettingsButton_Click(object sender, RoutedEventArgs e)
    {
        // Load current settings into UI
        LoadSettingsToUI();
        SettingsPanel.Visibility = Visibility.Visible;
    }

    private void CloseSettingsPanel_Click(object sender, RoutedEventArgs e)
    {
        SettingsPanel.Visibility = Visibility.Collapsed;
        _appSettings.Save();
    }

    private void LoadSettingsToUI()
    {
        DarkModeToggle.IsChecked = _appSettings.DarkMode;
        BrightnessSlider.Value = _appSettings.Brightness;
        ContrastSlider.Value = _appSettings.Contrast;
        SaturationSlider.Value = _appSettings.Saturation;
        SharpnessSlider.Value = _appSettings.Sharpness;
        ConfidenceSlider.Value = _appSettings.ConfidenceThreshold;
        MinCellAreaSlider.Value = _appSettings.MinCellArea;
        OverlayOpacitySlider.Value = _appSettings.OverlayOpacity;
    }

    private void DarkModeToggle_Click(object sender, RoutedEventArgs e)
    {
        _isDarkMode = DarkModeToggle.IsChecked == true;
        _appSettings.DarkMode = _isDarkMode;
        ApplyTheme(_isDarkMode);
        _appSettings.Save();
    }

    private void ApplyTheme(bool isDark)
    {
        // Define theme colors
        var bgColor = isDark ? "#1E1E2E" : "#F8F6F9";
        var surfaceColor = isDark ? "#2D2D3D" : "#FFFFFF";
        var textColor = isDark ? "#E4E4E7" : "#322935";
        var subtleTextColor = isDark ? "#A1A1AA" : "#5E5461";
        var accentColor = isDark ? "#8B5CF6" : "#6B4E71";
        var borderColor = isDark ? "#3F3F5A" : "#D1CCD6";
        var cardBgColor = isDark ? "#252535" : "#FFFFFF";

        // Apply to main window
        Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString(bgColor));

        // Update resource brushes if needed
        Resources["SurfaceBrush"] = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString(surfaceColor));
        Resources["SubtleTextBrush"] = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString(subtleTextColor));
    }

    private void ImageEnhancement_Changed(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (BrightnessSlider == null || ContrastSlider == null) return;

        // Update value displays
        BrightnessValueText.Text = $"{BrightnessSlider.Value:F0}";
        ContrastValueText.Text = $"{ContrastSlider.Value:F0}";
        SaturationValueText.Text = $"{SaturationSlider.Value:F0}";
        SharpnessValueText.Text = $"{SharpnessSlider.Value:F0}";

        // Save settings
        _appSettings.Brightness = BrightnessSlider.Value;
        _appSettings.Contrast = ContrastSlider.Value;
        _appSettings.Saturation = SaturationSlider.Value;
        _appSettings.Sharpness = SharpnessSlider.Value;

        // Apply to displayed image (if loaded)
        ApplyImageEnhancements();
    }

    private void ApplyImageEnhancements()
    {
        if (OriginalImage.Source == null) return;

        // Create effect for image enhancement
        // Using shader effects would be ideal, but for simplicity we'll adjust opacity/contrast via transforms
        double brightness = _appSettings.Brightness / 100.0;
        double contrast = 1.0 + (_appSettings.Contrast / 100.0);

        // For now, just update the transform - full image processing would require shader effects
        // This is a placeholder for visual feedback
    }

    private void ResetImageEnhancement_Click(object sender, RoutedEventArgs e)
    {
        BrightnessSlider.Value = 0;
        ContrastSlider.Value = 0;
        SaturationSlider.Value = 0;
        SharpnessSlider.Value = 0;

        _appSettings.Brightness = 0;
        _appSettings.Contrast = 0;
        _appSettings.Saturation = 0;
        _appSettings.Sharpness = 0;
        _appSettings.Save();
    }

    private void ConfidenceSlider_Changed(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (ConfidenceSlider == null) return;
        ConfidenceValueText.Text = $"{ConfidenceSlider.Value:F2}";
        _appSettings.ConfidenceThreshold = ConfidenceSlider.Value;
    }

    private void MinCellAreaSlider_Changed(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (MinCellAreaSlider == null) return;
        MinCellAreaValueText.Text = $"{MinCellAreaSlider.Value:F0}";
        _appSettings.MinCellArea = MinCellAreaSlider.Value;
    }

    private void OverlayOpacitySlider_Changed(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (OverlayOpacitySlider == null) return;
        OverlayOpacityValueText.Text = $"{OverlayOpacitySlider.Value:F0}%";
        _appSettings.OverlayOpacity = OverlayOpacitySlider.Value;

        // Apply to overlay image
        if (OverlayImage != null)
        {
            OverlayImage.Opacity = OverlayOpacitySlider.Value / 100.0;
        }
    }

    // =========================================================================
    // Zoom/Pan Handlers
    // =========================================================================
    private double _imageZoomLevel = 1.0;
    private const double ImageMinZoom = 0.1;
    private const double ImageMaxZoom = 10.0;
    private bool _isPanning;
    private System.Windows.Point _panStartPoint;
    private System.Windows.Point _panStartOffset;

    private void ImageScrollViewer_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (Keyboard.Modifiers != ModifierKeys.Control && sender is ScrollViewer)
        {
            // Zoom with scroll wheel (no Ctrl needed)
            e.Handled = true;

            double zoomDelta = e.Delta > 0 ? 0.1 : -0.1;
            _imageZoomLevel = Math.Clamp(_imageZoomLevel + zoomDelta * _imageZoomLevel, ImageMinZoom, ImageMaxZoom);

            // Apply zoom to all image transforms
            ApplyZoomToAllImages(_imageZoomLevel);
        }
    }

    private void ApplyZoomToAllImages(double zoom)
    {
        // Zoom functionality removed - images now fit to container automatically
    }

    private void ImageScrollViewer_PreviewMouseDown(object sender, MouseButtonEventArgs e)
    {
        // Middle mouse button for panning
        if (e.MiddleButton == MouseButtonState.Pressed && sender is ScrollViewer scrollViewer)
        {
            _isPanning = true;
            _panStartPoint = e.GetPosition(scrollViewer);
            _panStartOffset = new System.Windows.Point(scrollViewer.HorizontalOffset, scrollViewer.VerticalOffset);
            scrollViewer.CaptureMouse();
            scrollViewer.Cursor = Cursors.Hand;
            e.Handled = true;
        }
    }

    private void ImageScrollViewer_PreviewMouseMove(object sender, MouseEventArgs e)
    {
        if (_isPanning && sender is ScrollViewer scrollViewer)
        {
            var currentPoint = e.GetPosition(scrollViewer);
            var deltaX = currentPoint.X - _panStartPoint.X;
            var deltaY = currentPoint.Y - _panStartPoint.Y;

            scrollViewer.ScrollToHorizontalOffset(_panStartOffset.X - deltaX);
            scrollViewer.ScrollToVerticalOffset(_panStartOffset.Y - deltaY);
        }
    }

    private void ImageScrollViewer_PreviewMouseUp(object sender, MouseButtonEventArgs e)
    {
        if (_isPanning && sender is ScrollViewer scrollViewer)
        {
            _isPanning = false;
            scrollViewer.ReleaseMouseCapture();
            scrollViewer.Cursor = Cursors.Arrow;
            e.Handled = true;
        }
    }

    private void ResetImageZoom()
    {
        _imageZoomLevel = 1.0;
        ApplyZoomToAllImages(1.0);
    }

    // =========================================================================
    // ROI Selection Handlers
    // =========================================================================
    private bool _isDrawingROI;
    private System.Windows.Point _roiStartPoint;
    private Rectangle? _roiRectangle;
    private Int32Rect _currentROI;
    private int _roiImageWidth;
    private int _roiImageHeight;

    private void ROIButton_Click(object sender, RoutedEventArgs e)
    {
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;
        var originalPath = Path.Combine(baseDir, "original.png");

        if (!File.Exists(originalPath))
        {
            MessageBox.Show("Please load an image first.",
                "No Image", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        try
        {
            var imgSource = LoadImage(originalPath);
            ROIImage.Source = imgSource;

            // Reset zoom
            _roiZoomLevel = 1.0;
            if (ROIZoomTransform != null)
            {
                ROIZoomTransform.ScaleX = 1.0;
                ROIZoomTransform.ScaleY = 1.0;
            }

            if (imgSource is BitmapSource bmp)
            {
                _roiImageWidth = bmp.PixelWidth;
                _roiImageHeight = bmp.PixelHeight;
                // Set canvas and image to source dimensions
                // They will be scaled together via the parent Grid's ScaleTransform
                ROICanvas.Width = bmp.PixelWidth;
                ROICanvas.Height = bmp.PixelHeight;
                ROIImage.Width = bmp.PixelWidth;
                ROIImage.Height = bmp.PixelHeight;
            }

            ClearROIRectangle();
            _currentROI = Int32Rect.Empty;
            UpdateROIInfo();

            ROIPanel.Visibility = Visibility.Visible;
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to load image: {ex.Message}",
                "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void CloseROIPanel_Click(object sender, RoutedEventArgs e)
    {
        ROIPanel.Visibility = Visibility.Collapsed;
        // Reset zoom when closing
        _roiZoomLevel = 1.0;
        if (ROIZoomTransform != null)
        {
            ROIZoomTransform.ScaleX = 1.0;
            ROIZoomTransform.ScaleY = 1.0;
        }
    }

    // ROI panel zoom
    private double _roiZoomLevel = 1.0;
    private const double ROIMinZoom = 0.5;
    private const double ROIMaxZoom = 5.0;

    private void ROIScrollViewer_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (ROIZoomTransform == null) return;

        e.Handled = true;
        double zoomDelta = e.Delta > 0 ? 0.1 : -0.1;
        _roiZoomLevel = Math.Clamp(_roiZoomLevel + zoomDelta * _roiZoomLevel, ROIMinZoom, ROIMaxZoom);

        ROIZoomTransform.ScaleX = _roiZoomLevel;
        ROIZoomTransform.ScaleY = _roiZoomLevel;
    }

    private void ROICanvas_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        _isDrawingROI = true;
        _roiStartPoint = e.GetPosition(ROICanvas);
        ClearROIRectangle();

        _roiRectangle = new Rectangle
        {
            Stroke = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#FF5722")),
            StrokeThickness = 2,
            StrokeDashArray = new DoubleCollection { 5, 3 },
            Fill = new SolidColorBrush(System.Windows.Media.Color.FromArgb(50, 255, 87, 34))
        };

        Canvas.SetLeft(_roiRectangle, _roiStartPoint.X);
        Canvas.SetTop(_roiRectangle, _roiStartPoint.Y);
        ROICanvas.Children.Add(_roiRectangle);
        ROICanvas.CaptureMouse();
    }

    private void ROICanvas_MouseMove(object sender, MouseEventArgs e)
    {
        if (!_isDrawingROI || _roiRectangle == null) return;

        var currentPoint = e.GetPosition(ROICanvas);
        double x = Math.Min(_roiStartPoint.X, currentPoint.X);
        double y = Math.Min(_roiStartPoint.Y, currentPoint.Y);
        double width = Math.Abs(currentPoint.X - _roiStartPoint.X);
        double height = Math.Abs(currentPoint.Y - _roiStartPoint.Y);

        x = Math.Max(0, x);
        y = Math.Max(0, y);
        width = Math.Min(width, _roiImageWidth - x);
        height = Math.Min(height, _roiImageHeight - y);

        Canvas.SetLeft(_roiRectangle, x);
        Canvas.SetTop(_roiRectangle, y);
        _roiRectangle.Width = width;
        _roiRectangle.Height = height;

        _currentROI = new Int32Rect((int)x, (int)y, (int)width, (int)height);
        UpdateROIInfo();
    }

    private void ROICanvas_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (!_isDrawingROI) return;
        _isDrawingROI = false;
        ROICanvas.ReleaseMouseCapture();

        if (_currentROI.Width > 10 && _currentROI.Height > 10)
        {
            ROIStatusText.Text = $"ROI selected: {_currentROI.Width} × {_currentROI.Height} px";
        }
        else
        {
            ClearROIRectangle();
            _currentROI = Int32Rect.Empty;
            UpdateROIInfo();
            ROIStatusText.Text = "ROI too small. Please draw a larger region.";
        }
    }

    private void ClearROIRectangle()
    {
        if (_roiRectangle != null && ROICanvas.Children.Contains(_roiRectangle))
            ROICanvas.Children.Remove(_roiRectangle);
        _roiRectangle = null;
    }

    private void UpdateROIInfo()
    {
        if (_currentROI.IsEmpty || _currentROI.Width == 0)
        {
            ROI_X_Text.Text = "--";
            ROI_Y_Text.Text = "--";
            ROI_Width_Text.Text = "--";
            ROI_Height_Text.Text = "--";
        }
        else
        {
            ROI_X_Text.Text = $"{_currentROI.X} px";
            ROI_Y_Text.Text = $"{_currentROI.Y} px";
            ROI_Width_Text.Text = $"{_currentROI.Width} px";
            ROI_Height_Text.Text = $"{_currentROI.Height} px";
        }
    }

    private void SetROI(int x, int y, int width, int height)
    {
        x = Math.Max(0, Math.Min(x, _roiImageWidth - width));
        y = Math.Max(0, Math.Min(y, _roiImageHeight - height));
        width = Math.Min(width, _roiImageWidth - x);
        height = Math.Min(height, _roiImageHeight - y);

        _currentROI = new Int32Rect(x, y, width, height);
        ClearROIRectangle();

        _roiRectangle = new Rectangle
        {
            Stroke = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#FF5722")),
            StrokeThickness = 2,
            StrokeDashArray = new DoubleCollection { 5, 3 },
            Fill = new SolidColorBrush(System.Windows.Media.Color.FromArgb(50, 255, 87, 34)),
            Width = width,
            Height = height
        };

        Canvas.SetLeft(_roiRectangle, x);
        Canvas.SetTop(_roiRectangle, y);
        ROICanvas.Children.Add(_roiRectangle);
        UpdateROIInfo();
        ROIStatusText.Text = $"ROI selected: {width} × {height} px";
    }

    private void ROIPreset512_Click(object sender, RoutedEventArgs e)
    {
        SetROI((_roiImageWidth - 512) / 2, (_roiImageHeight - 512) / 2, 512, 512);
    }

    private void ROIPreset1024_Click(object sender, RoutedEventArgs e)
    {
        SetROI((_roiImageWidth - 1024) / 2, (_roiImageHeight - 1024) / 2, 1024, 1024);
    }

    private void ROIPresetCenter_Click(object sender, RoutedEventArgs e)
    {
        SetROI(_roiImageWidth / 4, _roiImageHeight / 4, _roiImageWidth / 2, _roiImageHeight / 2);
    }

    private void ROIPresetFull_Click(object sender, RoutedEventArgs e)
    {
        SetROI(0, 0, _roiImageWidth, _roiImageHeight);
    }

    private void ClearROI_Click(object sender, RoutedEventArgs e)
    {
        ClearROIRectangle();
        _currentROI = Int32Rect.Empty;
        UpdateROIInfo();
        ROIStatusText.Text = "ROI cleared. Draw a new region.";
    }

    private async void AnalyzeROI_Click(object sender, RoutedEventArgs e)
    {
        if (_currentROI.IsEmpty || _currentROI.Width < 10 || _currentROI.Height < 10)
        {
            MessageBox.Show("Please select a valid region of interest first.",
                "No ROI", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        ROIPanel.Visibility = Visibility.Collapsed;

        try
        {
            var baseDir = AppDomain.CurrentDomain.BaseDirectory;
            var originalPath = Path.Combine(baseDir, "original.png");
            var roiPath = Path.Combine(baseDir, "roi_temp.png");

            using (var original = new System.Drawing.Bitmap(originalPath))
            {
                var cropRect = new System.Drawing.Rectangle(_currentROI.X, _currentROI.Y, _currentROI.Width, _currentROI.Height);
                using (var cropped = original.Clone(cropRect, original.PixelFormat))
                {
                    // Smart resize for efficient processing
                    const int patchSize = 512;
                    const int maxPatches = 16; // Target max patches for fast processing

                    int roiWidth = cropped.Width;
                    int roiHeight = cropped.Height;

                    // Calculate optimal size
                    int targetSize = CalculateOptimalSize(roiWidth, roiHeight, patchSize, maxPatches);

                    if (targetSize > 0 && targetSize != Math.Max(roiWidth, roiHeight))
                    {
                        // Resize needed
                        double scale = (double)targetSize / Math.Max(roiWidth, roiHeight);
                        int newWidth = (int)(roiWidth * scale);
                        int newHeight = (int)(roiHeight * scale);

                        using (var resized = new System.Drawing.Bitmap(newWidth, newHeight))
                        {
                            using (var g = System.Drawing.Graphics.FromImage(resized))
                            {
                                g.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
                                g.DrawImage(cropped, 0, 0, newWidth, newHeight);
                            }
                            resized.Save(roiPath, System.Drawing.Imaging.ImageFormat.Png);
                        }
                    }
                    else
                    {
                        // No resize needed
                        cropped.Save(roiPath, System.Drawing.Imaging.ImageFormat.Png);
                    }
                }
            }

            _uploadedSamplePath = roiPath;
            OriginalImage.Source = LoadImage(roiPath);
            await RunPredictionSuiteAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to crop ROI: {ex.Message}",
                "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private static int CalculateOptimalSize(int width, int height, int patchSize, int maxPatches)
    {
        int maxDim = Math.Max(width, height);

        // If smaller than patch size, resize to patch size for single patch processing
        if (maxDim <= patchSize)
        {
            return patchSize;
        }

        // If small enough for efficient processing, keep original
        // Calculate approximate patch count with 75% overlap (stride = 128)
        int stride = patchSize / 4; // 128 for 512 patch
        int patchesX = (width - patchSize) / stride + 1;
        int patchesY = (height - patchSize) / stride + 1;
        int totalPatches = Math.Max(1, patchesX) * Math.Max(1, patchesY);

        if (totalPatches <= maxPatches)
        {
            return 0; // No resize needed
        }

        // Need to resize - find optimal size that gives ~maxPatches
        // Binary search for optimal size
        int low = patchSize;
        int high = maxDim;

        while (low < high)
        {
            int mid = (low + high + 1) / 2;
            double scale = (double)mid / maxDim;
            int scaledW = (int)(width * scale);
            int scaledH = (int)(height * scale);

            int px = Math.Max(1, (scaledW - patchSize) / stride + 1);
            int py = Math.Max(1, (scaledH - patchSize) / stride + 1);
            int patches = px * py;

            if (patches <= maxPatches)
            {
                low = mid;
            }
            else
            {
                high = mid - 1;
            }
        }

        return low;
    }

    // =========================================================================
    // Measurement Tool Handlers
    // =========================================================================
    private double _pixelSizeUm = 0.5; // µm per pixel (default for 20x)
    private bool _isMeasuring;
    private System.Windows.Point _measureStartPoint;
    private Line? _currentMeasureLine;
    private TextBlock? _currentMeasureLabel;
    private readonly List<MeasurementData> _measurements = new();
    private readonly List<UIElement> _measurementElements = new();

    private sealed class MeasurementData
    {
        public double PixelDistance { get; set; }
        public double MicrometerDistance { get; set; }
        public System.Windows.Point StartPoint { get; set; }
        public System.Windows.Point EndPoint { get; set; }
        public Line? LineElement { get; set; }
        public TextBlock? LabelElement { get; set; }
    }

    private void MeasureButton_Click(object sender, RoutedEventArgs e)
    {
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;
        var overlayPath = Path.Combine(baseDir, "overlay_predict.png");
        var originalPath = Path.Combine(baseDir, "original.png");

        var imagePath = File.Exists(overlayPath) ? overlayPath : originalPath;

        if (!File.Exists(imagePath))
        {
            MessageBox.Show("Please load an image first.",
                "No Image", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        try
        {
            MeasureImage.Source = LoadImage(imagePath);

            // Reset zoom
            _measureZoomLevel = 1.0;
            if (MeasureZoomTransform != null)
            {
                MeasureZoomTransform.ScaleX = 1.0;
                MeasureZoomTransform.ScaleY = 1.0;
            }

            // Clear previous measurements from canvas
            MeasureCanvas.Children.Clear();
            _measurements.Clear();
            _measurementElements.Clear();

            // Set canvas size to match image source dimensions
            // The canvas will be scaled along with the image via the parent Grid's ScaleTransform
            if (MeasureImage.Source is BitmapSource bmp)
            {
                MeasureCanvas.Width = bmp.PixelWidth;
                MeasureCanvas.Height = bmp.PixelHeight;
                MeasureImage.Width = bmp.PixelWidth;
                MeasureImage.Height = bmp.PixelHeight;
            }

            UpdateScaleBar();
            UpdateMeasurementStatistics();
            MeasurePanel.Visibility = Visibility.Visible;
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to load image: {ex.Message}",
                "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void CloseMeasurePanel_Click(object sender, RoutedEventArgs e)
    {
        MeasurePanel.Visibility = Visibility.Collapsed;
        // Reset zoom when closing
        _measureZoomLevel = 1.0;
        if (MeasureZoomTransform != null)
        {
            MeasureZoomTransform.ScaleX = 1.0;
            MeasureZoomTransform.ScaleY = 1.0;
        }
    }

    // Measure panel zoom
    private double _measureZoomLevel = 1.0;
    private const double MeasureMinZoom = 0.5;
    private const double MeasureMaxZoom = 5.0;

    private void MeasureScrollViewer_PreviewMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (MeasureZoomTransform == null) return;

        e.Handled = true;
        double zoomDelta = e.Delta > 0 ? 0.1 : -0.1;
        _measureZoomLevel = Math.Clamp(_measureZoomLevel + zoomDelta * _measureZoomLevel, MeasureMinZoom, MeasureMaxZoom);

        MeasureZoomTransform.ScaleX = _measureZoomLevel;
        MeasureZoomTransform.ScaleY = _measureZoomLevel;
    }

    private void ObjectiveComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        // Skip if UI not fully initialized (event fires during XAML parsing)
        if (!IsLoaded || PixelSizeTextBox == null || ObjectiveComboBox == null) return;

        // Typical pixel sizes for different objectives (approximations)
        // These depend on camera and microscope, but are common defaults
        var pixelSizes = new Dictionary<int, double>
        {
            { 0, 1.0 },   // 10x
            { 1, 0.5 },   // 20x
            { 2, 0.25 },  // 40x
            { 3, 0.17 },  // 60x
            { 4, 0.1 },   // 100x
            { 5, 0.5 }    // Custom (keep current)
        };

        var selectedIndex = ObjectiveComboBox.SelectedIndex;
        if (selectedIndex >= 0 && selectedIndex < 5)
        {
            _pixelSizeUm = pixelSizes[selectedIndex];
            PixelSizeTextBox.Text = _pixelSizeUm.ToString("F3");
            UpdateScaleBar();
            UpdateMeasurementLabels();
            UpdateMeasurementStatistics();
        }
    }

    private void PixelSizeTextBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        // Skip if UI not fully initialized
        if (!IsLoaded) return;

        if (double.TryParse(PixelSizeTextBox.Text, out var value) && value > 0)
        {
            _pixelSizeUm = value;
            UpdateScaleBar();
            UpdateMeasurementLabels();
            UpdateMeasurementStatistics();
        }
    }

    private void UpdateScaleBar()
    {
        // Skip if UI not fully initialized
        if (ScaleBarLine == null || ScaleBarText == null) return;

        // Calculate scale bar for a nice round number
        double[] niceValues = { 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000 };
        double targetPixelWidth = 100; // Target width in pixels

        double targetUm = targetPixelWidth * _pixelSizeUm;
        double bestValue = niceValues[0];

        foreach (var val in niceValues)
        {
            if (val <= targetUm * 1.5)
                bestValue = val;
        }

        double actualPixelWidth = bestValue / _pixelSizeUm;
        ScaleBarLine.Width = actualPixelWidth;
        ScaleBarText.Text = bestValue >= 1000 ? $"{bestValue / 1000:F0} mm" : $"{bestValue:F0} µm";
    }

    private void MeasureCanvas_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        _isMeasuring = true;
        _measureStartPoint = e.GetPosition(MeasureCanvas);

        // Create new line
        _currentMeasureLine = new Line
        {
            Stroke = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#FF5722")),
            StrokeThickness = 2,
            StrokeStartLineCap = PenLineCap.Round,
            StrokeEndLineCap = PenLineCap.Round,
            X1 = _measureStartPoint.X,
            Y1 = _measureStartPoint.Y,
            X2 = _measureStartPoint.X,
            Y2 = _measureStartPoint.Y
        };

        // Create label
        _currentMeasureLabel = new TextBlock
        {
            Background = new SolidColorBrush((System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#CC322935")),
            Foreground = Brushes.White,
            Padding = new Thickness(4, 2, 4, 2),
            FontSize = 11,
            FontWeight = FontWeights.SemiBold,
            Text = "0 µm"
        };

        MeasureCanvas.Children.Add(_currentMeasureLine);
        MeasureCanvas.Children.Add(_currentMeasureLabel);
        Canvas.SetLeft(_currentMeasureLabel, _measureStartPoint.X);
        Canvas.SetTop(_currentMeasureLabel, _measureStartPoint.Y - 20);

        MeasureCanvas.CaptureMouse();
    }

    private void MeasureCanvas_MouseMove(object sender, MouseEventArgs e)
    {
        if (!_isMeasuring || _currentMeasureLine == null || _currentMeasureLabel == null) return;

        var currentPoint = e.GetPosition(MeasureCanvas);
        _currentMeasureLine.X2 = currentPoint.X;
        _currentMeasureLine.Y2 = currentPoint.Y;

        // Calculate distance
        double dx = currentPoint.X - _measureStartPoint.X;
        double dy = currentPoint.Y - _measureStartPoint.Y;
        double pixelDistance = Math.Sqrt(dx * dx + dy * dy);
        double umDistance = pixelDistance * _pixelSizeUm;

        // Update label
        _currentMeasureLabel.Text = umDistance >= 1000
            ? $"{umDistance / 1000:F2} mm"
            : $"{umDistance:F1} µm";

        // Position label at midpoint
        double midX = (_measureStartPoint.X + currentPoint.X) / 2;
        double midY = (_measureStartPoint.Y + currentPoint.Y) / 2;
        Canvas.SetLeft(_currentMeasureLabel, midX);
        Canvas.SetTop(_currentMeasureLabel, midY - 20);

        // Update current measurement display
        CurrentMeasurementText.Text = umDistance >= 1000
            ? $"{umDistance / 1000:F2} mm"
            : $"{umDistance:F1} µm";
        CurrentMeasurementPixels.Text = $"({pixelDistance:F1} px)";
    }

    private void MeasureCanvas_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (!_isMeasuring || _currentMeasureLine == null || _currentMeasureLabel == null) return;

        _isMeasuring = false;
        MeasureCanvas.ReleaseMouseCapture();

        var endPoint = e.GetPosition(MeasureCanvas);
        double dx = endPoint.X - _measureStartPoint.X;
        double dy = endPoint.Y - _measureStartPoint.Y;
        double pixelDistance = Math.Sqrt(dx * dx + dy * dy);

        // Only save if distance is meaningful (> 5 pixels)
        if (pixelDistance > 5)
        {
            var measurement = new MeasurementData
            {
                PixelDistance = pixelDistance,
                MicrometerDistance = pixelDistance * _pixelSizeUm,
                StartPoint = _measureStartPoint,
                EndPoint = endPoint,
                LineElement = _currentMeasureLine,
                LabelElement = _currentMeasureLabel
            };

            _measurements.Add(measurement);
            _measurementElements.Add(_currentMeasureLine);
            _measurementElements.Add(_currentMeasureLabel);

            // Add to list
            var listItem = measurement.MicrometerDistance >= 1000
                ? $"{measurement.MicrometerDistance / 1000:F2} mm ({pixelDistance:F0} px)"
                : $"{measurement.MicrometerDistance:F1} µm ({pixelDistance:F0} px)";
            MeasurementsListBox.Items.Add(listItem);

            UpdateMeasurementStatistics();
            MeasureStatusText.Text = $"Added measurement: {listItem}";
        }
        else
        {
            // Remove tiny measurement
            MeasureCanvas.Children.Remove(_currentMeasureLine);
            MeasureCanvas.Children.Remove(_currentMeasureLabel);
        }

        _currentMeasureLine = null;
        _currentMeasureLabel = null;
    }

    private void MeasureCanvas_MouseRightButtonDown(object sender, MouseButtonEventArgs e)
    {
        // Find and remove the nearest measurement line
        var clickPoint = e.GetPosition(MeasureCanvas);
        MeasurementData? nearest = null;
        double minDistance = double.MaxValue;

        foreach (var m in _measurements)
        {
            // Calculate distance from click to line segment
            double dist = PointToLineDistance(clickPoint, m.StartPoint, m.EndPoint);
            if (dist < minDistance && dist < 20) // Within 20 pixels
            {
                minDistance = dist;
                nearest = m;
            }
        }

        if (nearest != null)
        {
            // Remove from canvas
            if (nearest.LineElement != null)
                MeasureCanvas.Children.Remove(nearest.LineElement);
            if (nearest.LabelElement != null)
                MeasureCanvas.Children.Remove(nearest.LabelElement);

            // Find and remove from list
            int index = _measurements.IndexOf(nearest);
            _measurements.Remove(nearest);
            if (index >= 0 && index < MeasurementsListBox.Items.Count)
                MeasurementsListBox.Items.RemoveAt(index);

            UpdateMeasurementStatistics();
            MeasureStatusText.Text = "Measurement deleted";
        }
    }

    private static double PointToLineDistance(System.Windows.Point p, System.Windows.Point lineStart, System.Windows.Point lineEnd)
    {
        double dx = lineEnd.X - lineStart.X;
        double dy = lineEnd.Y - lineStart.Y;
        double lengthSquared = dx * dx + dy * dy;

        if (lengthSquared == 0)
            return Math.Sqrt(Math.Pow(p.X - lineStart.X, 2) + Math.Pow(p.Y - lineStart.Y, 2));

        double t = Math.Max(0, Math.Min(1, ((p.X - lineStart.X) * dx + (p.Y - lineStart.Y) * dy) / lengthSquared));
        double projX = lineStart.X + t * dx;
        double projY = lineStart.Y + t * dy;

        return Math.Sqrt(Math.Pow(p.X - projX, 2) + Math.Pow(p.Y - projY, 2));
    }

    private void UpdateMeasurementLabels()
    {
        // Skip if UI not fully initialized
        if (MeasurementsListBox == null) return;

        // Update all measurement labels with new pixel size
        foreach (var m in _measurements)
        {
            m.MicrometerDistance = m.PixelDistance * _pixelSizeUm;
            if (m.LabelElement != null)
            {
                m.LabelElement.Text = m.MicrometerDistance >= 1000
                    ? $"{m.MicrometerDistance / 1000:F2} mm"
                    : $"{m.MicrometerDistance:F1} µm";
            }
        }

        // Update list
        MeasurementsListBox.Items.Clear();
        foreach (var m in _measurements)
        {
            var listItem = m.MicrometerDistance >= 1000
                ? $"{m.MicrometerDistance / 1000:F2} mm ({m.PixelDistance:F0} px)"
                : $"{m.MicrometerDistance:F1} µm ({m.PixelDistance:F0} px)";
            MeasurementsListBox.Items.Add(listItem);
        }
    }

    private void UpdateMeasurementStatistics()
    {
        // Skip if UI not fully initialized
        if (MeasureMeanText == null) return;

        if (_measurements.Count == 0)
        {
            MeasureMeanText.Text = "--";
            MeasureStdText.Text = "--";
            MeasureMinText.Text = "--";
            MeasureMaxText.Text = "--";
            return;
        }

        var values = _measurements.Select(m => m.MicrometerDistance).ToList();
        double mean = values.Average();
        double min = values.Min();
        double max = values.Max();
        double std = 0;

        if (values.Count > 1)
        {
            double sumSquares = values.Sum(v => Math.Pow(v - mean, 2));
            std = Math.Sqrt(sumSquares / (values.Count - 1));
        }

        string FormatValue(double v) => v >= 1000 ? $"{v / 1000:F2} mm" : $"{v:F1} µm";

        MeasureMeanText.Text = FormatValue(mean);
        MeasureStdText.Text = FormatValue(std);
        MeasureMinText.Text = FormatValue(min);
        MeasureMaxText.Text = FormatValue(max);
    }

    private void ClearMeasurements_Click(object sender, RoutedEventArgs e)
    {
        // Remove all measurement elements from canvas
        foreach (var element in _measurementElements)
        {
            MeasureCanvas.Children.Remove(element);
        }

        _measurements.Clear();
        _measurementElements.Clear();
        MeasurementsListBox.Items.Clear();

        CurrentMeasurementText.Text = "-- µm";
        CurrentMeasurementPixels.Text = "(-- px)";
        UpdateMeasurementStatistics();
        MeasureStatusText.Text = "All measurements cleared";
    }

    private void ExportMeasurements_Click(object sender, RoutedEventArgs e)
    {
        if (_measurements.Count == 0)
        {
            MessageBox.Show("No measurements to export.", "Export", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        var dialog = new SaveFileDialog
        {
            Title = "Export Measurements",
            Filter = "CSV files (*.csv)|*.csv|Text files (*.txt)|*.txt",
            DefaultExt = ".csv",
            FileName = $"measurements_{DateTime.Now:yyyyMMdd_HHmmss}"
        };

        if (dialog.ShowDialog() == true)
        {
            try
            {
                using var writer = new StreamWriter(dialog.FileName);
                writer.WriteLine("Measurement,Distance_um,Distance_px,Start_X,Start_Y,End_X,End_Y");

                for (int i = 0; i < _measurements.Count; i++)
                {
                    var m = _measurements[i];
                    writer.WriteLine($"{i + 1},{m.MicrometerDistance:F2},{m.PixelDistance:F2},{m.StartPoint.X:F1},{m.StartPoint.Y:F1},{m.EndPoint.X:F1},{m.EndPoint.Y:F1}");
                }

                // Add statistics
                writer.WriteLine();
                writer.WriteLine("Statistics");
                writer.WriteLine($"Pixel Size (um/px),{_pixelSizeUm:F4}");
                writer.WriteLine($"Count,{_measurements.Count}");

                if (_measurements.Count > 0)
                {
                    var values = _measurements.Select(m => m.MicrometerDistance).ToList();
                    writer.WriteLine($"Mean (um),{values.Average():F2}");
                    writer.WriteLine($"Min (um),{values.Min():F2}");
                    writer.WriteLine($"Max (um),{values.Max():F2}");

                    if (values.Count > 1)
                    {
                        double mean = values.Average();
                        double std = Math.Sqrt(values.Sum(v => Math.Pow(v - mean, 2)) / (values.Count - 1));
                        writer.WriteLine($"Std Dev (um),{std:F2}");
                    }
                }

                MessageBox.Show($"Measurements exported to:\n{dialog.FileName}",
                    "Export Complete", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Export failed: {ex.Message}",
                    "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }
    }

    // =========================================================================
    // Label Editor Handlers
    // =========================================================================
    private System.Drawing.Bitmap? _editableMask;
    private readonly Stack<System.Drawing.Bitmap> _maskUndoStack = new();
    private bool _isDrawing;
    private System.Windows.Point _lastDrawPoint;

    private void LabelEditorButton_Click(object sender, RoutedEventArgs e)
    {
        if (_isGuest)
        {
            MessageBox.Show("Label editing is only available for registered users.\nPlease login to use this feature.",
                "Feature Restricted", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        // Load the mask image for editing
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;
        var maskPath = Path.Combine(baseDir, "prediction_result_predict.png");
        var originalPath = Path.Combine(baseDir, "original.png");

        if (!File.Exists(maskPath) || !File.Exists(originalPath))
        {
            MessageBox.Show("Please run analysis first to generate a mask.",
                "No Mask Available", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        try
        {
            // Load original image
            LabelEditorImage.Source = LoadImage(originalPath);

            // Load mask as editable bitmap
            _editableMask = new System.Drawing.Bitmap(maskPath);
            _maskUndoStack.Clear();
            UpdateMaskDisplay();

            // Set canvas size
            LabelEditorCanvas.Width = _editableMask.Width;
            LabelEditorCanvas.Height = _editableMask.Height;

            LabelEditorPanel.Visibility = Visibility.Visible;
            LabelEditorStatus.Text = "Draw with brush or right-click to select labels";
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to load mask: {ex.Message}",
                "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void CloseLabelEditorButton_Click(object sender, RoutedEventArgs e)
    {
        LabelEditorPanel.Visibility = Visibility.Collapsed;
        _editableMask?.Dispose();
        _editableMask = null;
        foreach (var bmp in _maskUndoStack)
            bmp.Dispose();
        _maskUndoStack.Clear();
    }

    private void UpdateMaskDisplay()
    {
        if (_editableMask == null) return;

        // Convert to color mask for display
        var colorMask = CreateColorMaskFromLabels(_editableMask);
        LabelEditorMask.Source = BitmapToImageSource(colorMask);
        colorMask.Dispose();
    }

    private static System.Drawing.Bitmap CreateColorMaskFromLabels(System.Drawing.Bitmap labelMask)
    {
        var colorMask = new System.Drawing.Bitmap(labelMask.Width, labelMask.Height, System.Drawing.Imaging.PixelFormat.Format32bppArgb);

        // Color lookup table (ARGB format)
        var colors = new int[]
        {
            0x00000000,  // 0: Background (transparent)
            unchecked((int)0x9628A745),  // 1: Healthy (green with alpha 150)
            unchecked((int)0x96DC3545),  // 2: Affected (red with alpha 150)
            unchecked((int)0x96FFC107),  // 3: Irrelevant (yellow with alpha 150)
        };

        // Lock both bitmaps for fast access
        var srcRect = new System.Drawing.Rectangle(0, 0, labelMask.Width, labelMask.Height);
        var srcData = labelMask.LockBits(srcRect, System.Drawing.Imaging.ImageLockMode.ReadOnly, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        var dstData = colorMask.LockBits(srcRect, System.Drawing.Imaging.ImageLockMode.WriteOnly, System.Drawing.Imaging.PixelFormat.Format32bppArgb);

        unsafe
        {
            byte* srcPtr = (byte*)srcData.Scan0;
            int* dstPtr = (int*)dstData.Scan0;
            int pixelCount = labelMask.Width * labelMask.Height;

            for (int i = 0; i < pixelCount; i++)
            {
                // Read label from red channel (index 2 in BGRA)
                int label = srcPtr[i * 4 + 2];
                // Write color from lookup table
                dstPtr[i] = label < colors.Length ? colors[label] : 0;
            }
        }

        labelMask.UnlockBits(srcData);
        colorMask.UnlockBits(dstData);
        return colorMask;
    }

    private static BitmapSource BitmapToImageSource(System.Drawing.Bitmap bitmap)
    {
        var bitmapData = bitmap.LockBits(
            new System.Drawing.Rectangle(0, 0, bitmap.Width, bitmap.Height),
            System.Drawing.Imaging.ImageLockMode.ReadOnly,
            System.Drawing.Imaging.PixelFormat.Format32bppArgb);

        var source = BitmapSource.Create(
            bitmap.Width, bitmap.Height,
            96, 96,
            PixelFormats.Bgra32,
            null,
            bitmapData.Scan0,
            bitmapData.Stride * bitmap.Height,
            bitmapData.Stride);

        bitmap.UnlockBits(bitmapData);
        source.Freeze();
        return source;
    }

    private int GetSelectedClass()
    {
        if (BrushBackground.IsChecked == true) return 0;
        if (BrushHealthy.IsChecked == true) return 1;
        if (BrushAffected.IsChecked == true) return 2;
        if (BrushIrrelevant.IsChecked == true) return 3;
        return 1; // Default to healthy
    }

    private void SaveMaskState()
    {
        if (_editableMask == null) return;
        _maskUndoStack.Push((System.Drawing.Bitmap)_editableMask.Clone());
        // Keep only last 20 undo states
        while (_maskUndoStack.Count > 20)
        {
            var oldest = _maskUndoStack.ToArray()[^1];
            oldest.Dispose();
        }
    }

    private void LabelCanvas_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (_editableMask == null) return;

        if (SelectModeCheckbox.IsChecked == true)
        {
            // Selection mode - get label at click position
            var pos = e.GetPosition(LabelEditorCanvas);
            var x = (int)pos.X;
            var y = (int)pos.Y;

            if (x >= 0 && x < _editableMask.Width && y >= 0 && y < _editableMask.Height)
            {
                var pixel = _editableMask.GetPixel(x, y);
                var label = pixel.R;
                var labelNames = new[] { "Background", "Healthy", "Affected", "Irrelevant" };
                var labelName = label < labelNames.Length ? labelNames[label] : "Unknown";
                SelectedLabelInfo.Text = $"Selected: {labelName} (Class {label})\nAt position ({x}, {y})";
            }
            return;
        }

        // Drawing mode
        _isDrawing = true;
        _lastDrawPoint = e.GetPosition(LabelEditorCanvas);
        SaveMaskState();
        DrawAtPosition(_lastDrawPoint);
        LabelEditorCanvas.CaptureMouse();
    }

    private void LabelCanvas_MouseMove(object sender, MouseEventArgs e)
    {
        if (!_isDrawing || _editableMask == null) return;

        var currentPoint = e.GetPosition(LabelEditorCanvas);
        DrawLine(_lastDrawPoint, currentPoint);
        _lastDrawPoint = currentPoint;
    }

    private void LabelCanvas_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        _isDrawing = false;
        LabelEditorCanvas.ReleaseMouseCapture();
        UpdateMaskDisplay();
    }

    private void LabelCanvas_MouseRightButtonDown(object sender, MouseButtonEventArgs e)
    {
        // Right-click to select label
        if (_editableMask == null) return;

        var pos = e.GetPosition(LabelEditorCanvas);
        var x = (int)pos.X;
        var y = (int)pos.Y;

        if (x >= 0 && x < _editableMask.Width && y >= 0 && y < _editableMask.Height)
        {
            var pixel = _editableMask.GetPixel(x, y);
            var label = pixel.R;
            var labelNames = new[] { "Background", "Healthy", "Affected", "Irrelevant" };
            var labelName = label < labelNames.Length ? labelNames[label] : "Unknown";
            SelectedLabelInfo.Text = $"Selected: {labelName} (Class {label})\nAt position ({x}, {y})";
        }
    }

    private void DrawAtPosition(System.Windows.Point pos)
    {
        if (_editableMask == null) return;

        var brushSize = (int)BrushSizeSlider.Value;
        var classValue = GetSelectedClass();
        var color = System.Drawing.Color.FromArgb(classValue, classValue, classValue);

        using var g = System.Drawing.Graphics.FromImage(_editableMask);
        using var brush = new System.Drawing.SolidBrush(color);
        g.FillEllipse(brush, (float)pos.X - brushSize / 2f, (float)pos.Y - brushSize / 2f, brushSize, brushSize);
    }

    private void DrawLine(System.Windows.Point from, System.Windows.Point to)
    {
        if (_editableMask == null) return;

        var brushSize = (int)BrushSizeSlider.Value;
        var classValue = GetSelectedClass();
        var color = System.Drawing.Color.FromArgb(classValue, classValue, classValue);

        using var g = System.Drawing.Graphics.FromImage(_editableMask);
        using var pen = new System.Drawing.Pen(color, brushSize);
        pen.StartCap = System.Drawing.Drawing2D.LineCap.Round;
        pen.EndCap = System.Drawing.Drawing2D.LineCap.Round;
        g.DrawLine(pen, (float)from.X, (float)from.Y, (float)to.X, (float)to.Y);
    }

    private void LabelEditorUndo_Click(object sender, RoutedEventArgs e)
    {
        if (_maskUndoStack.Count == 0)
        {
            MessageBox.Show("Nothing to undo.", "Undo", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        _editableMask?.Dispose();
        _editableMask = _maskUndoStack.Pop();
        UpdateMaskDisplay();
        LabelEditorStatus.Text = "Undo successful";
    }

    private void LabelEditorSave_Click(object sender, RoutedEventArgs e)
    {
        if (_editableMask == null)
        {
            MessageBox.Show("No mask to save.", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        var result = MessageBox.Show(
            "Do you want to save the corrected mask?\n\nThis will overwrite the current prediction mask.",
            "Save Corrected Mask",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);

        if (result != MessageBoxResult.Yes) return;

        try
        {
            var baseDir = AppDomain.CurrentDomain.BaseDirectory;
            var maskPath = Path.Combine(baseDir, "prediction_result_predict.png");
            var backupPath = Path.Combine(baseDir, "prediction_result_predict_backup.png");

            // Create backup
            if (File.Exists(maskPath))
            {
                File.Copy(maskPath, backupPath, true);
            }

            // Save corrected mask
            _editableMask.Save(maskPath, System.Drawing.Imaging.ImageFormat.Png);

            // Update the main view
            MaskImage.Source = LoadImage(maskPath);

            MessageBox.Show("Mask saved successfully!\nBackup created as: prediction_result_predict_backup.png",
                "Save Complete", MessageBoxButton.OK, MessageBoxImage.Information);

            LabelEditorStatus.Text = "Mask saved successfully";
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to save mask: {ex.Message}",
                "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private string GenerateAIReport()
    {
        var reportScript = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "report_generator.py");

        var psi = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            WorkingDirectory = AppDomain.CurrentDomain.BaseDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        psi.ArgumentList.Add(reportScript);

        using var process = Process.Start(psi);
        if (process is null)
        {
            throw new InvalidOperationException("Failed to start report generator");
        }

        var output = process.StandardOutput.ReadToEnd();
        var error = process.StandardError.ReadToEnd();
        process.WaitForExit();

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException($"Report generation failed: {error}");
        }

        // Parse the output to find the report path
        // Look for "Report saved to:" or a line ending with .pdf
        var lines = output.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
        foreach (var line in lines)
        {
            var trimmed = line.Trim();

            // Check for "Report saved to: <path>"
            if (trimmed.Contains("Report saved to:", StringComparison.OrdinalIgnoreCase))
            {
                var colonIndex = trimmed.LastIndexOf(':');
                if (colonIndex >= 0 && colonIndex < trimmed.Length - 1)
                {
                    var path = trimmed.Substring(colonIndex + 1).Trim();
                    if (path.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase) && File.Exists(path))
                    {
                        return path;
                    }
                }
            }

            // Also check for any path ending with .pdf
            if (trimmed.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase))
            {
                if (File.Exists(trimmed))
                {
                    return trimmed;
                }
            }
        }

        // Look for recently created PDF files in base directory
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;
        var recentPdf = Directory.GetFiles(baseDir, "analysis_report_*.pdf")
            .OrderByDescending(f => File.GetCreationTime(f))
            .FirstOrDefault();

        if (!string.IsNullOrEmpty(recentPdf) && File.Exists(recentPdf))
        {
            return recentPdf;
        }

        throw new InvalidOperationException("Report was generated but file could not be found.");
    }
}
