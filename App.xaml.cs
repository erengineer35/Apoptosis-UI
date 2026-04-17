using System.Windows;
// Resolve ambiguous references with System.Windows.Forms
using Application = System.Windows.Application;
using MessageBox = System.Windows.MessageBox;

namespace ApoptosisUI;

/// <summary>
/// Interaction logic for App.xaml
/// </summary>
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // Show login window first
        var loginWindow = new LoginWindow();
        var loginResult = loginWindow.ShowDialog();

        if (loginResult == true)
        {
            try
            {
                // Login successful - show main window with user info
                var mainWindow = new MainWindow(loginWindow.LoggedInUsername, loginWindow.IsGuest);
                mainWindow.Show();
            }
            catch (System.Exception ex)
            {
                MessageBox.Show($"Failed to start main application:\n\n{ex.Message}\n\n{ex.StackTrace}",
                    "Startup Error", MessageBoxButton.OK, MessageBoxImage.Error);
                Shutdown();
            }
        }
        else
        {
            // Login cancelled - exit application
            Shutdown();
        }
    }
}

